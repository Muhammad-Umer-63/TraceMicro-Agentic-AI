"""Separate PetClinic global-plan development variant; original runner unchanged."""
import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from importlib.metadata import version
from pathlib import Path
import sys
import time

from petclinic_batch_groq import BatchGroqProvider, GlobalBudget, PreparedBatchWorkflow, token_totals
from petclinic_batch_prototype import SERVICES, TOOLS, batches, collect
from tracemicro.action_schema import closed
from tracemicro.langgraph_workflow import LangGraphWorkflow
from tracemicro.pilot import ROOT, make_store
from tracemicro.providers import GroqConfig, ProviderError
from tracemicro.workflow import Budget, validate_output

VERSION = 'global_plan_compact_v3_bounded_output'
PLANNING_INPUT_CAP = 12000
PLAN_RESPONSIBILITY_CHARACTERS = 160
PLAN_CITATIONS_PER_SERVICE = 2


def planning_context(evidence, ledger):
    """Deterministic declaration anchors and complete saved outgoing typed edges."""
    names = sorted(row['class'] for row in ledger)
    identifiers = {name: 'C'+str(i+1) for i, name in enumerate(names)}
    prefix = 'org.springframework.samples.petclinic.'
    compact, provenance = {}, {}
    for row in ledger:
        for eid in row['evidence_ids']:
            record = evidence[eid]
            item = {'class': identifiers[row['class']]}
            if record['tool'] == 'inspect_source':
                declarations = [line for line in record['lines']
                    if re.search(r'\b(class|interface|enum|record)\s+\w+', line['text'])
                    and not line['text'].lstrip().startswith(('*', '//'))]
                anchor = declarations[0] if declarations else None
                item.update(declaration=anchor['text'].strip()[:160] if anchor else None,
                            line=anchor['line'] if anchor else None)
                provenance[eid] = {'class': row['class'], 'path': record['path'], 'sha256': record['sha256'],
                    'original_excerpt_end': record['end_line'], 'original_partial': row['source_excerpt_is_partial'],
                    'declaration_characters_max': 160,
                    'declaration_clipped': bool(anchor and len(anchor['text'].strip()) > 160)}
            else:
                edges = sorted({(identifiers[e['target']], e['type']) for e in record['outgoing']})
                item['outgoing'] = [list(edge) for edge in edges]
                provenance[eid] = {'class': row['class'], 'original_evidence_id': eid,
                    'policy': 'All outgoing target/type pairs, deduplicated; occurrences omitted; incoming derivable globally.'}
            compact[eid] = item
    context = {'state': {'scope': list(identifiers.values()), 'services': SERVICES, 'evidence': compact},
        'class_names': {code: name.removeprefix(prefix) for name, code in identifiers.items()},
        'class_name_prefix': prefix,
        'source_excerpt_coverage': [{'class': identifiers[row['class']],
            'source_total_lines': row['source_total_lines'],
            'source_excerpt_end_line': row['source_excerpt_end_line'],
            'source_excerpt_is_partial': row['source_excerpt_is_partial']} for row in ledger if row['source_excerpt_is_partial']],
        'coverage_policy': 'Only the six partial original excerpts are listed. Planner sees declaration anchors only for ALL classes.',
        'evidence_legend': 'Each source E record quotes at most160 characters of the first declaration-like line in the first80 source lines. '
            'It may be incomplete or absent. Dependency E records list all outgoing [target_class_ID,relationship_type] pairs. '
            'C IDs map to class_names. E IDs cite original records via a saved provenance map.',
        'allowed_service_labels': SERVICES,
        'omissions': 'No method bodies, fields, imports, annotations, full source excerpts, occurrence weights, '
            'edge source lines, runtime/database evidence or held-out mappings. No inferred business-role labels.'}
    return context, provenance


def save(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


class PlanSessionBudget(GlobalBudget):
    """Fixed authorized session, reusing charging/cooldown/deadline mechanics."""
    def __init__(self, path, *, clock=None, sleeper=None):
        super().__init__(clock=clock, sleeper=sleeper)
        self.max_requests, self.max_wait = 40, 2340
        self.checkpoint_path = (ROOT / path).resolve()
        self.checkpoint_path.relative_to(ROOT)
        self.deadline_monotonic = self.clock()+3600
        if self.checkpoint_path.exists():
            previous = json.loads(self.checkpoint_path.read_text(encoding='utf-8'))
            if [previous[k] for k in ['max_requests', 'interval', 'max_wait']] != [40, 60, 2340]:
                raise ValueError('Session limits cannot change')
            for key in ['requests', 'wait_total', 'last_finished', 'deadline_monotonic']:
                setattr(self, key, previous[key])


def plan_schema():
    service = closed({'label': {'type': 'string', 'enum': SERVICES},
                      'responsibility': {'type': 'string'},
                      'evidence': {'type': 'array', 'items': {'type': 'string'}}})
    output = closed({'services': {'type': 'array', 'items': service}})
    return {'type': 'json_schema', 'json_schema': {'name': 'tracemicro_plan_v1', 'strict': True,
        'schema': closed({'action': closed({'type': {'type': 'string', 'enum': ['submit']}, 'output': output})})}}


def validate_plan(plan, evidence):
    if not isinstance(plan, dict) or set(plan) != {'services'} or not isinstance(plan['services'], list):
        return ['invalid_plan_schema']
    if not 1 <= len(plan['services']) <= len(SERVICES):
        return ['invalid_plan_count']
    findings, labels = [], set()
    for row in plan['services']:
        if not isinstance(row, dict) or set(row) != {'label', 'responsibility', 'evidence'}:
            findings.append('invalid_plan_service'); continue
        label = row['label']
        if not isinstance(label, str) or label not in SERVICES or label in labels:
            findings.append('invalid_plan_label')
        else:
            labels.add(label)
        if not isinstance(row['responsibility'], str) or not row['responsibility'].strip():
            findings.append('empty_responsibility')
        refs = row['evidence']
        if not isinstance(refs, list) or not refs or any(not isinstance(e, str) or e not in evidence for e in refs):
            findings.append('invalid_plan_evidence')
    return findings


class PlanProvider(BatchGroqProvider):
    def prepare_request(self, messages):
        request = super().prepare_request(messages)
        request['body']['response_format'] = plan_schema()
        return request

    def structured_instructions(self):
        instruction = ('Propose one to five candidate services with distinct responsibilities grounded in supplied evidence. '
            'Use allowed labels and cite real evidence IDs for each responsibility. No class assignments are requested. '
            'Choose a single service if justified by the evidence; no minimum separation is required. '
            'Evidence is compressed: declaration anchors and typed dependency summaries, not full source. '
            'Partial source warnings apply. Return only the strict action envelope with type submit and output.services.')
        return instruction, instruction


def validate_bounded_plan(plan, evidence):
    findings = validate_plan(plan, evidence)
    if findings:
        return findings
    for row in plan['services']:
        if len(row['responsibility']) > PLAN_RESPONSIBILITY_CHARACTERS:
            findings.append('plan_responsibility_too_long')
        if len(row['evidence']) > PLAN_CITATIONS_PER_SERVICE or len(set(row['evidence'])) != len(row['evidence']):
            findings.append('plan_citations_not_bounded_distinct')
    return findings


class BoundedPlanProvider(PlanProvider):
    def structured_instructions(self):
        wire, system = super().structured_instructions()
        bound = (' Keep each responsibility to one concise sentence of at most160characters. '
                 'Cite only one or two distinct strongest evidence IDs per service; do not enumerate every class.')
        return wire+bound, system+bound


class PlannedBatchWorkflow(PreparedBatchWorkflow):
    def __init__(self, *args, service_plan, **kwargs):
        self.service_plan = service_plan
        super().__init__(*args, **kwargs)

    def context(self):
        context = super().context()
        # Remove the concrete assignment example, not only its first label.
        context['action_schema'] = {'submit': {'description': 'Submit assignments matching the strict wire schema. '
            'Each row supplies class, services, shared and same-class evidence IDs.'}}
        context['global_service_plan'] = self.service_plan
        context['batch_guidance'] += (' Assign according to the planned responsibilities; cite current same-class evidence. '
            'The plan is a model proposal, not reference truth. Report assignments honestly, including sharing.')
        return context


def run(output_dir, budget, *, allow_live=False, transport=None):
    if not allow_live and transport is None:
        raise ValueError('Explicit live authorization required')
    folder = (ROOT / output_dir).resolve()
    folder.relative_to(ROOT)
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    before_requests, before_wait = budget.requests, budget.wait_total
    store = make_store()
    evidence, ledger = collect(store)
    for row in ledger:
        for eid in row['evidence_ids']:
            if evidence[eid]['tool'] == 'inspect_source':
                evidence[eid]['source_total_lines'] = row['source_total_lines']
                evidence[eid]['source_excerpt_is_partial'] = row['source_excerpt_is_partial']
    save(folder/'precollection.json', {'evidence': evidence, 'ledger': ledger, 'tool_reads': len(evidence)})
    config = GroqConfig('openai/gpt-oss-20b', max_requests=2, max_output_tokens=1024,
                       timeout_seconds=15, max_input_bytes=64000, structured_outputs=True)
    planning_config = GroqConfig('openai/gpt-oss-20b', max_requests=1, max_output_tokens=1024,
                       timeout_seconds=15, max_input_bytes=PLANNING_INPUT_CAP, structured_outputs=True)
    experiment_path = ROOT/'configs/petclinic_global_plan_compact_v3.json'
    experiment = json.loads(experiment_path.read_text(encoding='utf-8'))
    save(folder/'experiment.json', experiment)
    summary = {'version': VERSION, 'run_kind': 'groq_live' if transport is None else 'groq_simulated_http',
        'runtime_versions': {'python': sys.version, 'langgraph': version('langgraph')},
        'experiment_sha256': hashlib.sha256(experiment_path.read_bytes()).hexdigest(),
        'created_utc': datetime.now(timezone.utc).isoformat(), 'source_fingerprint': store.snapshot['eligible_java_files_sha256'],
        'dependency_json_sha256': store.graph_sha256, 'provider_config': asdict(config),
        'planning_provider_config': asdict(planning_config), 'allowed_service_labels': SERVICES,
        'batch_sizes': [len(s) for s in batches(store.classes)], 'batch_order': store.classes,
        'code_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__).resolve(), ROOT/'petclinic_batch_groq.py', ROOT/'tracemicro/workflow.py',
                      ROOT/'tracemicro/providers.py', ROOT/'tracemicro/langgraph_workflow.py',
                      ROOT/'tracemicro/action_schema.py', ROOT/'petclinic_batch_prototype.py',
                      ROOT/'tracemicro/pilot.py', ROOT/'tracemicro/evidence.py']},
        'architectural_accuracy': None, 'cost': None, 'plan': None, 'planning_findings': [],
        'evidence_policy': 'Planner sees deterministic declaration/dependency summaries of50records; '
            'batches retain local original first80line excerpts/dependencies plus plan. No additional evidence.',
        'limits': {'session_requests': budget.max_requests, 'session_wait_seconds': budget.max_wait,
                   'session_deadline_monotonic': budget.deadline_monotonic, 'planning_requests': 1,
                   'batch_requests': 2, 'nonempty_services_minimum': 1, 'nonempty_services_forced': False}}
    accepted, outcomes, records = [], [], []

    def checkpoint(status):
        summary.update(status=status, accepted_assignments=accepted, batches=outcomes,
            combined_findings=validate_output({'assignments': accepted}, store.classes,
                summary['allowed_service_labels'], evidence, TOOLS),
            global_transport_attempts=budget.requests-before_requests,
            session_transport_attempts=budget.requests, global_wait_seconds=budget.wait_total-before_wait,
            session_wait_seconds=budget.wait_total, **token_totals(records),
            live_model_run=transport is None and budget.requests > before_requests,
            total_elapsed_seconds=time.monotonic()-started)
        save(folder/'summary.json', summary)

    checkpoint('prepared')
    provider = BoundedPlanProvider(planning_config, budget, allow_live=allow_live, transport=transport,
                            clock=budget.clock, sleeper=budget.sleep)
    context, provenance = planning_context(evidence, ledger)
    save(folder/'planning_provenance.json', provenance)
    planning = {'context': context, 'status': 'prepared', 'model_usage': provider.records}
    save(folder/'planning.json', planning)
    try:
        action = provider.decide(context)
        plan = action.get('output') if action.get('type') == 'submit' else None
        findings = validate_bounded_plan(plan, evidence)
        planning.update(status='invalid_plan' if findings else 'accepted', output=plan, findings=findings)
        summary.update(plan=plan, planning_findings=findings)
    except Exception as error:
        planning.update(status='error', error_type=type(error).__name__)
        if isinstance(error, ProviderError):
            planning.update(error_code=error.code, http_status=error.status)
    records.extend(provider.records)
    save(folder/'planning.json', planning)
    if planning['status'] != 'accepted':
        checkpoint('failed_plan'); return summary
    labels = [row['label'] for row in plan['services']]
    summary['allowed_service_labels'] = labels
    checkpoint('planned')
    for index, scope in enumerate(batches(store.classes)):
        provider = BatchGroqProvider(config, budget, allowed_services=labels, allow_live=allow_live,
                                     transport=transport, clock=budget.clock, sleeper=budget.sleep)
        core = PlannedBatchWorkflow(store, provider, scope, labels, Budget(2, 0, 1),
            service_plan=plan, required_evidence_tools=TOOLS,
            excerpt_ledger=[r for r in ledger if r['class'] in scope], previous_assignments=copy.deepcopy(accepted),
            run_metadata={'version': VERSION, 'batch': index+1, 'service_plan': plan,
                          'source_policy': 'first80lines plus saved full-graph dependencies'})
        core.state.evidence = {eid: record for eid, record in evidence.items() if record['class'] in scope}
        item = {'batch': index+1, 'scope': scope}
        try:
            doc = LangGraphWorkflow(core, allow_live=allow_live).run(folder/f'batch_{index+1:02}.json')
            item.update(stop=doc['state']['termination_reason'], findings=doc['state']['verification_findings'],
                        errors=[e for e in doc['events'] if e['kind'] == 'error'])
            if item['stop'] == 'basic_checks_passed':
                accepted.extend(doc['state']['candidate_assignments'])
        except Exception as error:
            item.update(stop='runner_error', error_type=type(error).__name__)
            save(folder/f'batch_{index+1:02}_incomplete.json',
                 {'state': asdict(core.state), 'events': core.events, 'model_usage': provider.records})
        records.extend(provider.records)
        outcomes.append(item)
        checkpoint('in_progress' if item['stop'] == 'basic_checks_passed' else 'failed_batch')
        if item['stop'] != 'basic_checks_passed':
            return summary
    checkpoint('basic_checks_passed' if not summary['combined_findings'] else 'combined_validation_failed')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live', action='store_true')
    parser.add_argument('--session-ledger', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    if not args.allow_live:
        parser.error('--allow-live required')
    budget = PlanSessionBudget(Path(args.session_ledger))
    budget.save()
    result = run(Path(args.output_dir), budget, allow_live=True)
    print(json.dumps({key: result[key] for key in ['status', 'global_transport_attempts',
        'session_transport_attempts', 'reported_tokens', 'total_elapsed_seconds']}, indent=2))
    raise SystemExit(result['status'] != 'basic_checks_passed')


if __name__ == '__main__':
    main()
