import copy
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Budget:
    decisions: int = 8
    tool_calls: int = 4
    revisions: int = 1

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in asdict(self).values()):
            raise ValueError('Budgets must be nonnegative integers')


@dataclass
class State:
    scope: list
    services: list
    budget: Budget
    candidate_assignments: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    verification_findings: list = field(default_factory=list)
    revisions: list = field(default_factory=list)
    status: str = 'ready'
    termination_reason: str = ''


def validate_output(output, scope, services, evidence, required_evidence_tools=()):
    findings = []
    def issue(code, **details):
        findings.append({'code':code, **details})
    if not isinstance(output, dict) or set(output) != {'assignments'} or not isinstance(output['assignments'], list):
        return [{'code':'invalid_output_schema'}]
    seen = set()
    for row in output['assignments']:
        if not isinstance(row,dict) or set(row) != {'class','services','shared','evidence'}:
            issue('invalid_assignment_schema'); continue
        name = row['class']
        if not isinstance(name,str):
            issue('invalid_class'); continue
        if name not in scope: issue('unknown_or_out_of_scope_class', class_name=name)
        if name in seen: issue('duplicate_class_record', class_name=name)
        seen.add(name)
        domains = row['services']
        if not isinstance(domains,list) or not domains or any(not isinstance(d,str) for d in domains):
            issue('invalid_services',class_name=name)
        elif len(set(domains)) != len(domains) or any(d not in services for d in domains):
            issue('unknown_or_duplicate_service',class_name=name)
        elif type(row['shared']) is not bool or (len(domains)>1) != row['shared']:
            issue('invalid_shared_declaration',class_name=name)
        refs = row['evidence']
        if not isinstance(refs,list) or not refs or any(not isinstance(e,str) or e not in evidence or evidence[e]['class'] != name for e in refs):
            issue('invalid_or_missing_evidence',class_name=name)
        else:
            observed={evidence[e]['tool'] for e in refs}
            for tool in sorted(set(required_evidence_tools)-observed):
                issue('required_evidence_missing',class_name=name,tool=tool)
    for name in sorted(set(scope)-seen): issue('missing_class',class_name=name)
    return findings


class Workflow:
    def __init__(self, store, provider, scope, services, budget=None, *, required_evidence_tools=(), run_metadata=None):
        if not scope or len(set(scope)) != len(scope) or not set(scope) <= set(store.classes):
            raise ValueError('Scope must contain unique known classes')
        if not services or any(not isinstance(s,str) or not s.strip() for s in services) or len(set(services)) != len(services):
            raise ValueError('Service names must be unique nonempty strings')
        self.store, self.provider = store, provider
        self.state = State(sorted(scope), sorted(services), copy.deepcopy(budget or Budget()))
        if not set(required_evidence_tools) <= {'inspect_source','inspect_dependencies'}:
            raise ValueError('Unknown required evidence tool')
        self.required_evidence_tools=tuple(sorted(set(required_evidence_tools)))
        self.run_metadata=copy.deepcopy(run_metadata or {})
        self.events = []

    def event(self, kind, **data):
        self.events.append({'sequence':len(self.events)+1,'kind':kind,
                            'timestamp_utc':datetime.now(timezone.utc).isoformat(),**copy.deepcopy(data)})

    def stop(self, reason):
        self.state.status = 'stopped'
        self.state.termination_reason = reason
        self.event('terminated',reason=reason)

    def progress(self):
        rows = []
        candidates = self.state.candidate_assignments if isinstance(self.state.candidate_assignments,list) else []
        for name in self.state.scope:
            ids = {}
            duplicates = []
            unique_results = []
            for evidence_id, result in self.state.evidence.items():
                if result['class'] != name:
                    continue
                ids.setdefault(result['tool'], []).append(evidence_id)
                if result in unique_results:
                    duplicates.append(evidence_id)
                else:
                    unique_results.append(result)
            rows.append({'class':name, 'available_evidence_ids_by_tool':ids,
                         'pending_evidence_tools':sorted(set(self.required_evidence_tools)-set(ids)),
                         'candidate_record_present':any(isinstance(r,dict) and r.get('class') == name
                                                        for r in candidates),
                         'duplicate_result_ids':duplicates})
        return rows

    def context(self):
        progress = self.progress()
        pending = next((r for r in progress if r['pending_evidence_tools']), progress[0])
        return {'instruction':'Return one action object with a mandatory top-level string field "type": inspect_source, inspect_dependencies or submit. Follow the object examples below; do not return the examples map. Class keys are exact names. Evidence IDs must come from tools. Source actions may optionally add integer start_line and end_line fields. Investigate pending evidence across the ENTIRE state.scope; avoid repeating identical inspections. Every submission must include exactly one record for EVERY scoped class, with required same-class evidence IDs cited. A shared class uses one record with multiple services and does not replace other scoped classes. Never invent evidence or assignments. per_class_progress is refreshed from available evidence; candidate_record_present is not validation or architectural correctness. state.verification_findings are historical findings from the last submission; tools do not update that history. Available evidence must still be cited in the next submission.',
                'action_schema':{'inspect_source':{'type':'inspect_source','class':next((r['class'] for r in progress if 'inspect_source' in r['pending_evidence_tools']),pending['class'])},
                                 'inspect_dependencies':{'type':'inspect_dependencies','class':next((r['class'] for r in progress if 'inspect_dependencies' in r['pending_evidence_tools']),pending['class'])},
                                 'submit':{'type':'submit','output':{'assignments':[{'class':pending['class'],'services':[self.state.services[0]],'shared':False,'evidence':['E1']}]}}},
                'allowed_service_labels':list(self.state.services),
                'service_label_rule':'Every services value must exactly match an allowed_service_labels entry. Multiple distinct allowed labels require shared=true. Examples are shapes, not class assignments.',
                'required_evidence_tools_per_assignment':list(self.required_evidence_tools),
                'per_class_progress':progress,
                'current_candidate_findings':validate_output({'assignments':self.state.candidate_assignments},self.state.scope,self.state.services,self.state.evidence,self.required_evidence_tools),
                'state':asdict(self.state)}

    def run(self, output_path):
        target = self.store._inside(output_path)
        if target.exists(): raise ValueError('Refusing to overwrite trace: '+str(target))
        self.state.status = 'investigating'
        self.event('started',mode=self.provider.kind,scope=self.state.scope,budget=asdict(self.state.budget))
        while self.state.status == 'investigating':
            if self.state.budget.decisions == 0:
                self.stop('decision_budget_exhausted'); break
            self.state.budget.decisions -= 1
            context = self.context()
            self.event('decision_requested',context=context)
            try:
                action = self.provider.decide(copy.deepcopy(context))
                self.event('decision_received',action=action)
                if not isinstance(action,dict): raise ValueError('Action must be an object')
                kind = action.get('type')
                if kind in {'inspect_source','inspect_dependencies'}:
                    allowed = {'type','class','start_line','end_line'} if kind == 'inspect_source' else {'type','class'}
                    if set(action)-allowed or not {'type','class'} <= set(action): raise ValueError('Invalid tool arguments')
                    if self.state.budget.tool_calls == 0:
                        self.stop('tool_budget_exhausted'); break
                    self.state.budget.tool_calls -= 1
                    if action['class'] not in self.state.scope: raise ValueError('Class outside investigation scope')
                    if kind == 'inspect_source':
                        result = self.store.inspect_source(action['class'],action.get('start_line',1),action.get('end_line'))
                    else:
                        result = self.store.inspect_dependencies(action['class'])
                    evidence_id = 'E'+str(len(self.state.evidence)+1)
                    self.state.evidence[evidence_id] = result
                    self.event('tool_result',arguments=action,evidence_id=evidence_id,result=result)
                elif kind == 'submit':
                    if set(action) != {'type','output'}: raise ValueError('Invalid submit action')
                    findings = validate_output(action['output'],self.state.scope,self.state.services,self.state.evidence,self.required_evidence_tools)
                    previous = copy.deepcopy(self.state.candidate_assignments)
                    candidate = action['output'].get('assignments',[]) if isinstance(action['output'],dict) else []
                    self.state.candidate_assignments = copy.deepcopy(candidate)
                    self.state.verification_findings = findings
                    self.event('verification',candidate=action['output'],findings=findings,
                               interpretation='Basic schema/evidence-reference checks only, not architectural correctness')
                    if previous:
                        self.state.revisions.append({'before':previous,'after':copy.deepcopy(candidate)})
                    if not findings:
                        self.stop('basic_checks_passed')
                    elif self.state.budget.revisions == 0:
                        self.stop('revision_budget_exhausted')
                    else:
                        self.state.budget.revisions -= 1
                else: raise ValueError('Unknown action type')
            except StopIteration:
                self.stop('script_exhausted')
            except Exception as error:
                # Do not log exception text that a future transport might populate with secrets.
                from tracemicro.providers import ProviderError
                details = {'code':error.code,'http_status':error.status,'error_source':error.source} if isinstance(error,ProviderError) else {}
                if isinstance(error,ProviderError) and error.provider_error is not None:
                    details['provider_error']=error.provider_error
                self.event('error',error_type=type(error).__name__,**details)
                self.stop('action_or_provider_error')
        document = {'run_kind':self.provider.kind,
                    'live_model_run':self.provider.kind == 'groq_live' and getattr(self.provider,'http_requests_sent',0)>0,
                    'provenance':{'source_snapshot':self.store.snapshot,
                                  'dependency_json_sha256':self.store.graph_sha256,
                                  'identity_limit':'filename/package mapping, not compiler resolution'},
                    'state':asdict(self.state),'events':self.events,
                    'run_config':self.run_metadata,
                    'model_usage':getattr(self.provider,'records',None),'architectural_accuracy':None}
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf-8') as stream:
            json.dump(document,stream,indent=2); stream.write('\n')
        return document
