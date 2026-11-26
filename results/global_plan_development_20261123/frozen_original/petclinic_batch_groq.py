"""Sequential fixed-evidence PetClinic batches; live requires explicit opt-in."""
import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import time

from petclinic_batch_prototype import SERVICES, TOOLS, batches, collect, combine
from tracemicro.langgraph_workflow import LangGraphWorkflow
from tracemicro.action_schema import response_schema
from tracemicro.pilot import ROOT, make_store
from tracemicro.providers import GroqConfig, GroqProvider, ProviderError
from tracemicro.workflow import Budget, Workflow


class GlobalBudget:
    """One controller for all providers; charge transport attempts, never retry."""
    def __init__(self, max_requests=18, interval=60, max_wait=1020, *, clock=None, sleeper=None,
                 deadline_monotonic=None, checkpoint_path=None):
        if type(max_requests) is not int or not 1<=max_requests<=24:
            raise ValueError('Global request cap must be 1..24')
        if not 0<=interval<=60 or not 0<=max_wait<=1380:
            raise ValueError('Invalid global pacing limits')
        self.max_requests, self.interval, self.max_wait = max_requests, interval, max_wait
        self.clock, self.sleep = clock or time.monotonic, sleeper or time.sleep
        self.requests, self.wait_total, self.last_finished = 0, 0, None
        self.deadline_monotonic=deadline_monotonic
        self.checkpoint_path=Path(checkpoint_path).resolve() if checkpoint_path else None
        if self.checkpoint_path:
            self.checkpoint_path.relative_to(ROOT)
            if self.checkpoint_path.exists():
                saved=json.loads(self.checkpoint_path.read_text())
                if [saved[k] for k in ['max_requests','interval','max_wait']] != [max_requests,interval,max_wait]:
                    raise ValueError('Session limits cannot change between attempts')
                self.requests,self.wait_total,self.last_finished=saved['requests'],saved['wait_total'],saved['last_finished']
                self.deadline_monotonic=saved['deadline_monotonic']

    def save(self):
        if self.checkpoint_path:
            record={name:getattr(self,name) for name in ['max_requests','interval','max_wait','requests',
                    'wait_total','last_finished','deadline_monotonic']}
            self.checkpoint_path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.checkpoint_path.with_suffix('.pending.json')
            tmp.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
            tmp.replace(self.checkpoint_path)

    def finish(self):
        self.last_finished=self.clock()
        self.save()

    def acquire(self):
        if self.requests >= self.max_requests:
            raise ProviderError('global_request_cap')
        wait = 0 if self.last_finished is None else max(0,self.interval-(self.clock()-self.last_finished))
        if self.deadline_monotonic is not None and self.clock()+wait+15>=self.deadline_monotonic:
            raise ProviderError('session_wall_time_limit')
        if self.wait_total+wait > self.max_wait:
            raise ProviderError('global_pacing_wait_budget_exhausted')
        if wait: self.sleep(wait)
        self.wait_total += wait
        self.requests += 1
        self.save() # Charge before transport, including if the process later fails.
        return wait


class BatchGroqProvider(GroqProvider):
    def __init__(self, config, global_budget, *, allowed_services=SERVICES, **kwargs):
        super().__init__(config, **kwargs)
        self.global_budget = global_budget
        # Use only enum, already used by this schema's action type fields.
        self.allowed_services = tuple(allowed_services)
        response_schema(self.allowed_services,allowed_actions=('submit',))

    def structured_instructions(self):
        return (
            'Return exactly {"action":{"type":"submit","output":{"assignments":[...]}}}. '
            'Evidence is already collected; submit is the only allowed action. Cover every scoped class, '
            'cite its real evidence IDs, and use only allowed_service_labels. Multiple service labels require shared=true.',
            'Return only the strict-schema action envelope with type=submit. No tool actions, extra fields, markdown or hidden reasoning. '
            'Use exact scoped class names, allowed service labels and real same-class evidence IDs. Preserve shared-class records.')

    def prepare_request(self, messages):
        request = super().prepare_request(messages)
        if self.config.structured_outputs:
            request['body']['response_format'] = response_schema(self.allowed_services,allowed_actions=('submit',))
        return request

    def _pace(self):
        self.last_pacing_wait = self.global_budget.acquire()
        self.pacing_wait_total += self.last_pacing_wait

    def _request(self, method, url, body=None):
        before = self.global_budget.requests
        try:
            return super()._request(method,url,body)
        finally:
            if self.global_budget.requests > before:
                # Includes failed transport attempts. Persists across providers.
                self.global_budget.finish()


class PreparedBatchWorkflow(Workflow):
    def __init__(self, *args, excerpt_ledger, previous_assignments, **kwargs):
        super().__init__(*args, **kwargs)
        self.excerpt_ledger = excerpt_ledger
        self.previous_assignments = previous_assignments

    def context(self):
        context = super().context()
        context['action_schema'] = {'submit':context['action_schema']['submit']}
        context['instruction'] = 'Precollected batch: submit is the only supported action; follow batch_guidance and the submit schema.'
        example = context['action_schema']['submit']['output']['assignments'][0]
        example['evidence'] = [eid for eid,record in self.state.evidence.items()
                               if record['class'] == example['class']]
        context['source_excerpt_coverage'] = self.excerpt_ledger
        context['previous_accepted_assignments_for_global_label_consistency'] = self.previous_assignments
        context['batch_guidance'] = ('Evidence is precollected. Submit all current scoped classes using existing evidence IDs. '
            'No further inspections are budgeted. Partial source excerpts are NOT complete files; '
            'do not claim unseen code was inspected. Use the SAME global service labels across batches; '
            'prior accepted assignments provide context, not reference truth. Shared classes use one row with multiple labels. '
            'Allowed literal service labels: '+json.dumps(self.state.services)+'. '
            'On unknown_or_duplicate_service findings, repair invalid or repeated labels using only that list; '
            'do not repeat the rejected submission unchanged.')
        candidates = self.state.candidate_assignments
        context['service_label_feedback'] = [{'class':row.get('class'),
            'invalid_labels':[s for s in row['services'] if s not in self.state.services]}
            for row in candidates if isinstance(row,dict) and isinstance(row.get('services'),list)
            and any(s not in self.state.services for s in row['services'])] if isinstance(candidates,list) else []
        return context


def token_totals(records):
    sums, missing = {}, {}
    for key in ['prompt_tokens','completion_tokens','total_tokens']:
        values = [(r.get('usage') or {}).get(key) for r in records]
        valid = [v for v in values if type(v) is int and v>=0]
        sums[key] = sum(valid) if valid else None
        missing[key] = len(values)-len(valid)
    return {'reported_tokens':sums,'records_missing_token_fields':missing}


def run(output_dir, *, model='openai/gpt-oss-20b', allow_live=False, transport=None,
        max_requests=18, interval=60, max_wait=1020, clock=None, sleeper=None, global_budget=None):
    if transport is None and not allow_live:
        raise ValueError('Explicit --allow-live required; no key read or request made')
    # Dependency failure must occur before any potential request.
    from langgraph.graph import StateGraph  # noqa: F401
    budget = global_budget or GlobalBudget(max_requests,interval,max_wait,clock=clock,sleeper=sleeper)
    attempt_start_requests,attempt_start_wait=budget.requests,budget.wait_total
    config = GroqConfig(model,max_requests=2,max_output_tokens=1024,timeout_seconds=15,
                        max_input_bytes=64000,structured_outputs=True)
    folder = (ROOT/Path(output_dir)).resolve()
    folder.relative_to(ROOT)
    folder.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    store = make_store()
    prep_start = time.monotonic()
    evidence, ledger = collect(store)
    prep_elapsed = time.monotonic()-prep_start
    for item in ledger:
        for eid in item['evidence_ids']:
            if evidence[eid]['tool']=='inspect_source':
                evidence[eid]['source_total_lines'] = item['source_total_lines']
                evidence[eid]['source_excerpt_is_partial'] = item['source_excerpt_is_partial']
    (folder/'precollection.json').write_text(json.dumps({'evidence':evidence,'ledger':ledger,
        'tool_reads':len(evidence),'elapsed_seconds':prep_elapsed},indent=2)+'\n',encoding='utf-8')
    scopes = batches(store.classes)
    accepted, outcomes, all_records = [], [], []
    summary = {'run_kind':'groq_simulated_http' if transport is not None else 'groq_live',
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'source_fingerprint':store.snapshot['eligible_java_files_sha256'],
        'dependency_json_sha256':store.graph_sha256,
        'code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__).resolve(),ROOT/'tracemicro/langgraph_workflow.py',
                      ROOT/'tracemicro/providers.py',ROOT/'petclinic_batch_prototype.py',
                      ROOT/'tracemicro/action_schema.py',ROOT/'tracemicro/workflow.py']},
        'limits':{'global_requests':max_requests,'requests_per_batch':2,'max_output_tokens':1024,
                  'global_requested_completion_token_cap':max_requests*1024,
                  'interval_seconds':interval,'global_wait_seconds':max_wait,
                  'socket_timeout_seconds':15,'request_bytes':64000,
                  'additional_tools_per_batch':0,'corrections_per_batch':1},
        'provider_config':asdict(config),'precollection_reads':len(evidence),
        'allowed_service_labels':list(SERVICES),'service_schema_enum_enabled':True,'allowed_actions':['submit'],
        'precollection_elapsed_seconds':prep_elapsed,'batch_sizes':[len(s) for s in scopes],
        'cost':None,'cost_note':'No billing/pricing supplied; missing usage is unknown, not zero.',
        'architectural_accuracy':None}

    def checkpoint(status):
        summary.update(status=status,batches=outcomes,accepted_assignments=accepted,
            combined_findings=combine(accepted,store.classes,evidence),
            global_transport_attempts=budget.requests-attempt_start_requests,
            global_wait_seconds=budget.wait_total-attempt_start_wait,
            session_transport_attempts=budget.requests,session_wait_seconds=budget.wait_total,
            provider_request_records=len(all_records),**token_totals(all_records),
            live_model_run=transport is None and budget.requests>attempt_start_requests,
            total_elapsed_seconds=time.monotonic()-started)
        # Only this newly created run's checkpoint is updated; never old results.
        temporary = folder/'summary.pending.json'
        temporary.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        temporary.replace(folder/'summary.json')

    checkpoint('prepared')
    for index, scope in enumerate(scopes):
        before_count, before_wait = budget.requests, budget.wait_total
        batch_started = time.monotonic()
        provider = BatchGroqProvider(config,budget,allow_live=allow_live,transport=transport,
                                     clock=budget.clock,sleeper=budget.sleep)
        local = {eid:r for eid,r in evidence.items() if r['class'] in scope}
        core = PreparedBatchWorkflow(store,provider,scope,SERVICES,Budget(2,0,1),
            required_evidence_tools=TOOLS,
            excerpt_ledger=[r for r in ledger if r['class'] in scope],
            previous_assignments=copy.deepcopy(accepted),
            run_metadata={'batch':index+1,'global_limits':summary['limits'],
                'allowed_service_labels':list(SERVICES),'service_schema_enum_enabled':True,
                'allowed_actions':['submit'],
                'provider_config':asdict(config),'precollected_tool_reads':len(local),
                'fixed_evidence_policy':'first80lines plus saved full-graph dependencies'})
        core.state.evidence = local
        item = {'batch':index+1,'scope':scope}
        failed = False
        try:
            doc = LangGraphWorkflow(core,allow_live=allow_live).run(folder/f'batch_{index+1:02}.json')
            item.update(stop=doc['state']['termination_reason'],
                last_candidate=doc['state']['candidate_assignments'],
                findings=doc['state']['verification_findings'],
                errors=[e for e in doc['events'] if e['kind']=='error'])
            failed = item['stop']!='basic_checks_passed'
            if not failed: accepted.extend(doc['state']['candidate_assignments'])
        except Exception as error:
            # Preserve what exists on unexpected graph/serialization failures;
            # never persist raw exception text, headers, keys or response bodies.
            failed = True
            item.update(stop='runner_error',error_type=type(error).__name__,
                        last_candidate=core.state.candidate_assignments,
                        findings=core.state.verification_findings)
            (folder/f'batch_{index+1:02}_incomplete.json').write_text(json.dumps({
                'state':asdict(core.state),'events':core.events,'model_usage':provider.records,
                'runner_error_type':type(error).__name__},indent=2)+'\n',encoding='utf-8')
        all_records.extend(provider.records)
        item.update(transport_attempts=budget.requests-before_count,
                    provider_request_records=len(provider.records),
                    wait_seconds=budget.wait_total-before_wait,
                    elapsed_seconds=time.monotonic()-batch_started,**token_totals(provider.records))
        outcomes.append(item)
        checkpoint('failed_batch' if failed else 'in_progress')
        if failed: return summary
    checkpoint('basic_checks_passed' if not summary['combined_findings'] else 'combined_validation_failed')
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live',action='store_true')
    parser.add_argument('--model',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--max-requests',type=int,default=18)
    parser.add_argument('--pace-seconds',type=float,default=60)
    parser.add_argument('--max-wait-seconds',type=float,default=1020)
    args=parser.parse_args()
    if not args.allow_live: parser.error('Live CLI requires --allow-live; no request made')
    result=run(args.output_dir,model=args.model,allow_live=True,max_requests=args.max_requests,
               interval=args.pace_seconds,max_wait=args.max_wait_seconds)
    print(json.dumps({k:result[k] for k in ['status','global_transport_attempts','reported_tokens','global_wait_seconds','total_elapsed_seconds']},indent=2))
    if result['status']!='basic_checks_passed': raise SystemExit(1)


if __name__=='__main__': main()
