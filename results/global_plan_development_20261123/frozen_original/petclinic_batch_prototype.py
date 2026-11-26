"""Offline-only full PetClinic batching prototype; assignments are artificial."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from tracemicro.langgraph_workflow import LangGraphWorkflow
from tracemicro.pilot import make_store, ROOT
from tracemicro.providers import ScriptedProvider
from tracemicro.workflow import Budget, Workflow, validate_output

SERVICES = ['candidate_'+str(i) for i in range(1,6)]
TOOLS = ('inspect_source','inspect_dependencies')


def collect(store):
    """Exactly two deterministic reads/class; source excerpts explicitly bounded."""
    evidence, ledger = {}, []
    for name in store.classes:
        source = store.inspect_source(name)
        dependency = store.inspect_dependencies(name)
        ids = []
        for result in [source, dependency]:
            eid = 'E'+str(len(evidence)+1)
            evidence[eid] = result
            ids.append(eid)
        total = len(store.files[name]['lines'])
        ledger.append({'class':name, 'evidence_ids':ids,
                       'source_total_lines':total,
                       'source_excerpt_end_line':source['end_line'],
                       'source_excerpt_is_partial':source['end_line']<total})
    return evidence, ledger


def batches(names, size=3):
    return [names[i:i+size] for i in range(0,len(names),size)]


def combine(rows, scope, evidence):
    # Never deduplicate, auto-fill or accept an incomplete combined result.
    return validate_output({'assignments':rows},scope,SERVICES,evidence,TOOLS)


def run(output_dir):
    folder = (ROOT/Path(output_dir)).resolve()
    folder.relative_to(ROOT)
    folder.mkdir(parents=True,exist_ok=False)
    store = make_store()
    evidence, ledger = collect(store)
    scopes = batches(store.classes)
    rows, outcomes = [], []
    for index, scope in enumerate(scopes):
        local_evidence = {eid:r for eid,r in evidence.items() if r['class'] in scope}
        # Deliberately artificial fixture, NOT source-derived classification:
        # first global class shared, all others assigned to candidate_1.
        assignments = [{'class':name,'services':SERVICES[:2] if name==store.classes[0] else SERVICES[:1],
                        'shared':name==store.classes[0],
                        'evidence':[eid for eid,r in local_evidence.items() if r['class']==name]}
                       for name in scope]
        core = Workflow(store,ScriptedProvider([{'type':'submit','output':{'assignments':assignments}}]),
            scope,SERVICES,Budget(decisions=2,tool_calls=0,revisions=1),
            required_evidence_tools=TOOLS,
            run_metadata={'mode':'artificial_full_scope_batch_prototype',
                'assignments_are_synthetic':True,
                'precollection_reads':2*len(scope),
                'evidence_policy':'first80sourceLines plus saved whole-graph dependencies',
                'no_additional_model_selected_tools':True})
        core.state.evidence = local_evidence
        doc = LangGraphWorkflow(core).run(folder/f'batch_{index+1:02}.json')
        outcomes.append({'batch':index+1,'scope':scope,'stop':doc['state']['termination_reason']})
        if doc['state']['termination_reason'] != 'basic_checks_passed':
            break  # Never continue or silently discard a failed batch.
        rows.extend(doc['state']['candidate_assignments'])
    findings = combine(rows,store.classes,evidence)
    summary = {'mode':'offline_artificial_assignment_prototype',
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'live_model_run':False,'actual_model_requests':0,'model_tokens':None,'billing_cost':None,
        'source_fingerprint':store.snapshot['eligible_java_files_sha256'],
        'dependency_json_sha256':store.graph_sha256,
        'classes':len(store.classes),'batch_sizes':[len(s) for s in scopes],
        'precollection_tool_reads':len(evidence),'precollection_ledger':ledger,
        'proposed_live_caps_not_executed':{'max_requests_per_batch':2,'max_requests_global':2*len(scopes),
            'max_output_tokens_per_request':1024,'max_requested_completion_tokens_global':2048*len(scopes),
            'max_additional_tool_calls':0,'max_corrections_per_batch':1},
        'outcomes':outcomes,'assignments':rows,'combined_findings':findings,
        'architectural_accuracy':None,
        'limitation':'Artificial mappings test assembly/validation only; no architectural interpretation.'}
    (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['mode','classes','batch_sizes','precollection_tool_reads',
                                          'actual_model_requests','combined_findings']},indent=2))
    if findings: raise SystemExit(1)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,help='New workspace-local directory')
    run(parser.parse_args().output_dir)
