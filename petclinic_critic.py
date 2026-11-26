"""Separate advisory critic with fixed/selective/off routing; never applies changes."""
import argparse
from dataclasses import asdict
import hashlib
import json
import time

from petclinic_batch_groq import BatchGroqProvider, token_totals
from petclinic_batch_prototype import TOOLS
from petclinic_global_plan import PlanSessionBudget, planning_context, save
from tracemicro.action_schema import closed
from tracemicro.pilot import ROOT, inside, make_store
from tracemicro.providers import GroqConfig, ProviderError
from tracemicro.workflow import validate_output

KINDS = ['unsupported_assignment', 'shared_concern', 'boundary_concern', 'insufficient_evidence']
RULE = 'critic_policy_v1: selective invokes once when local validation has findings OR fewer than two nonempty services; fixed always invokes once; off never invokes'


def should_review(mode, rows, findings):
    if mode not in ('off', 'fixed', 'selective'):
        raise ValueError('Unknown critic mode')
    return mode == 'fixed' or mode == 'selective' and (bool(findings) or len({s for row in rows for s in row['services']}) < 2)


class CriticProvider(BatchGroqProvider):
    def prepare_request(self, messages):
        request = super().prepare_request(messages)
        issue = closed({'class': {'type': 'string'}, 'kind': {'type': 'string', 'enum': KINDS},
            'evidence': {'type': 'array', 'items': {'type': 'string'}}, 'explanation': {'type': 'string'},
            'proposed_services': {'type': 'array', 'items': {'type': 'string', 'enum': list(self.allowed_services)}},
            'proposed_shared': {'type': 'boolean'}})
        schema = closed({'action': closed({'type': {'type': 'string', 'enum': ['submit']},
                        'output': closed({'issues': {'type': 'array', 'items': issue}})})})
        request['body']['response_format'] = {'type': 'json_schema', 'json_schema': {
            'name': 'tracemicro_critic_v1', 'strict': True, 'schema': schema}}
        return request

    def structured_instructions(self):
        text = ('Independently challenge the supplied class assignments using only the evidence summaries. '
            'No generator dialogue or reference labels are supplied. Use full scoped class names for issues. '
            'Cite real evidence IDs, including at least one for the issue class. Explain uncertainty and source omissions. '
            'Proposed services must use allowed labels. Empty proposed_services means no correction proposed and proposed_shared=false. '
            'An empty issues array is allowed. No correction is automatically accepted. '
            'Return the strict submit envelope with output.issues; no hidden reasoning or extra fields.')
        return text, text


def validate_critique(output, scope, labels, evidence):
    if not isinstance(output, dict) or set(output) != {'issues'} or not isinstance(output['issues'], list):
        return ['invalid_critic_schema']
    findings = []
    keys = {'class', 'kind', 'evidence', 'explanation', 'proposed_services', 'proposed_shared'}
    for issue in output['issues']:
        if not isinstance(issue, dict) or set(issue) != keys:
            findings.append('invalid_issue'); continue
        name = issue['class']
        if name not in scope or issue['kind'] not in KINDS:
            findings.append('invalid_issue_class_or_kind')
        refs = issue['evidence']
        valid_refs = isinstance(refs, list) and bool(refs) and all(isinstance(e, str) and e in evidence for e in refs)
        if not valid_refs or not any(evidence[e]['class'] == name for e in refs):
            findings.append('invalid_issue_evidence')
        if not isinstance(issue['explanation'], str) or not issue['explanation'].strip():
            findings.append('missing_issue_explanation')
        proposed = issue['proposed_services']
        if not isinstance(proposed, list) or any(not isinstance(s, str) or s not in labels for s in proposed) or len(set(proposed)) != len(proposed):
            findings.append('invalid_proposal_labels')
        elif type(issue['proposed_shared']) is not bool or issue['proposed_shared'] != (len(proposed) > 1):
            findings.append('invalid_proposal_sharing')
    return findings


def run(source, output, budget, mode, *, allow_live=False, transport=None):
    folder = inside(output)
    folder.mkdir(parents=True, exist_ok=False)
    source = inside(source)
    summary = json.loads((source/'summary.json').read_text(encoding='utf-8'))
    prep = json.loads((source/'precollection.json').read_text(encoding='utf-8'))
    store = make_store()
    if summary['source_fingerprint'] != store.snapshot['eligible_java_files_sha256'] or summary['dependency_json_sha256'] != store.graph_sha256:
        raise ValueError('Saved run input mismatch')
    rows = summary['accepted_assignments']
    labels = summary['allowed_service_labels']
    findings = validate_output({'assignments': rows}, store.classes, labels, prep['evidence'], TOOLS)
    selected = should_review(mode, rows, findings)
    result = {'version': 'advisory_critic_v1', 'mode': mode, 'selection_rule': RULE,
        'run_kind': ('groq_live' if transport is None else 'groq_simulated_http') if selected else 'offline_routing',
        'selected': selected, 'source': str(source.relative_to(ROOT)), 'source_status': summary['status'],
        'source_summary_sha256': hashlib.sha256((source/'summary.json').read_bytes()).hexdigest(),
        'local_findings': findings, 'corrections_applied': False, 'architectural_accuracy': None,
        'code_sha256': hashlib.sha256(inside('petclinic_critic.py').read_bytes()).hexdigest()}
    started = time.monotonic()
    before, before_wait = budget.requests, budget.wait_total
    records = []
    if selected:
        context, provenance = planning_context(prep['evidence'], prep['ledger'])
        context['state']['scope'] = store.classes
        context['proposed_assignments'] = rows
        context['deterministic_findings'] = findings
        config = GroqConfig('openai/gpt-oss-20b', max_requests=1, max_output_tokens=1024,
                            timeout_seconds=15, max_input_bytes=20000, structured_outputs=True)
        result['provider_config'] = asdict(config)
        save(folder/'context.json', context)
        save(folder/'provenance.json', provenance)
        provider = CriticProvider(config, budget, allowed_services=labels, allow_live=allow_live,
                                 transport=transport, clock=budget.clock, sleeper=budget.sleep)
        try:
            action = provider.decide(context)
            output_value = action.get('output') if action.get('type') == 'submit' else None
            checked = validate_critique(output_value, store.classes, labels, prep['evidence'])
            result.update(status='critic_checked' if not checked else 'invalid_critique',
                          output=output_value, validation_findings=checked)
        except Exception as error:
            result.update(status='critic_failed', error_type=type(error).__name__)
            if isinstance(error, ProviderError):
                result.update(error_code=error.code, http_status=error.status)
        records = provider.records
    else:
        result['status'] = 'critic_skipped'
    result.update(global_transport_attempts=budget.requests-before, session_transport_attempts=budget.requests,
                  wait_seconds=budget.wait_total-before_wait, elapsed_seconds=time.monotonic()-started,
                  **token_totals(records), model_usage=records,
                  live_model_run=transport is None and budget.requests > before)
    save(folder/'summary.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--session-ledger', required=True)
    parser.add_argument('--mode', choices=['off', 'fixed', 'selective'], required=True)
    parser.add_argument('--allow-live', action='store_true')
    args = parser.parse_args()
    if args.mode != 'off' and not args.allow_live:
        parser.error('--allow-live required for potential critic requests')
    budget = PlanSessionBudget(inside(args.session_ledger))
    budget.save()
    result = run(args.source, args.output_dir, budget, args.mode, allow_live=args.allow_live)
    print(json.dumps({k: result[k] for k in ['status', 'global_transport_attempts', 'reported_tokens']}))
    raise SystemExit(result['status'] not in ('critic_checked', 'critic_skipped'))
