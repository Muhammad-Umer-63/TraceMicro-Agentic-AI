"""Offline three-class development comparison; no clustering or quality scoring."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

from baseline import analyze

ROOT = Path(__file__).resolve().parent
SCOPE = ['org.springframework.samples.petclinic.model.BaseEntity',
         'org.springframework.samples.petclinic.owner.Owner',
         'org.springframework.samples.petclinic.vet.Vet']


def inside(path):
    path = (ROOT/path).resolve()
    path.relative_to(ROOT)
    return path


def group_rows(groups, *, source_paths=False):
    """One row per original membership; never hide duplicate memberships."""
    rows = []
    for group, members in groups.items():
        for member in members:
            name = group+'.'+Path(member).stem if source_paths else member
            rows.append({'class':name, 'services':[group], 'shared':False})
    return rows


def summarize_assignments(rows, scope, universe):
    """Coverage means unique scoped identifiers with a nonempty service list.

    Presence/coverage is not validity. Known other classes are intentionally
    excluded, unknown inputs are reported, and shared rows remain single rows.
    """
    counts = Counter()
    assigned, present, unknown, excluded = set(), set(), set(), set()
    projected, invalid = [], []
    for index, row in enumerate(rows):
        if not isinstance(row,dict) or not isinstance(row.get('class'),str):
            invalid.append({'record_index':index, 'code':'invalid_class_record'})
            continue
        name = row['class']
        if name not in universe:
            unknown.add(name)
        if name not in scope:
            if name in universe:
                excluded.add(name)
            continue
        counts[name] += 1
        present.add(name)
        projected.append(row)
        services = row.get('services')
        if not isinstance(services,list) or not services or any(not isinstance(s,str) or not s.strip() for s in services):
            invalid.append({'record_index':index, 'class':name, 'code':'invalid_services'})
            continue
        assigned.add(name)
        if len(set(services)) != len(services):
            invalid.append({'record_index':index, 'class':name, 'code':'duplicate_service_label'})
        if type(row.get('shared')) is not bool or row['shared'] != (len(set(services)) > 1):
            invalid.append({'record_index':index, 'class':name, 'code':'invalid_shared_declaration'})
    return {'scope_class_count':len(scope), 'assigned_unique_class_count':len(assigned),
            'assignment_coverage':len(assigned)/len(scope),
            'missing_class_records':sorted(set(scope)-present),
            'unassigned_classes':sorted(set(scope)-assigned),
            'duplicate_class_records':{n:c for n,c in sorted(counts.items()) if c>1},
            'unknown_classes_in_input':sorted(unknown),
            'known_out_of_scope_classes_excluded':sorted(excluded),
            'invalid_records':invalid, 'assignments':projected,
            'represented_group_count':len({s for r in projected
                if isinstance(r.get('services'),list) for s in r['services'] if isinstance(s,str)})}


def recorded_resources(trace):
    records = trace.get('model_usage')
    records = records if isinstance(records,list) else []
    events = trace.get('events',[])
    tokens, missing = {}, {}
    for key in ['prompt_tokens','completion_tokens','total_tokens']:
        values = [(r.get('usage') or {}).get(key) for r in records]
        valid = [v for v in values if type(v) is int and v>=0]
        tokens[key] = sum(valid) if valid else None
        missing[key] = len(values)-len(valid)
    waits = [r.get('pacing_wait_seconds') for r in records]
    waits = [w for w in waits if type(w) in (int,float) and w>=0]
    elapsed = None
    if events:
        try:
            elapsed = (datetime.fromisoformat(events[-1]['timestamp_utc'])-
                       datetime.fromisoformat(events[0]['timestamp_utc'])).total_seconds()
            if elapsed < 0:
                elapsed = None
        except (KeyError,TypeError,ValueError):
            pass
    return {'source':'Recorded saved trace; no requests made by this comparison',
            'run_kind':trace.get('run_kind'), 'live_model_run':trace.get('live_model_run'),
            'execution_engine':trace.get('execution_engine'),
            'model_request_records':len(records),
            'parsed_model_responses':sum(r.get('status')=='parsed' for r in records),
            'reported_tokens':tokens, 'records_missing_token_fields':missing,
            'reported_pacing_wait_seconds':sum(waits) if waits else None,
            'records_missing_pacing':len(records)-len(waits),
            'recorded_elapsed_seconds_including_pacing':elapsed,
            'tool_action_attempts':sum(e.get('kind')=='decision_received' and
                isinstance(e.get('action'),dict) and e['action'].get('type') in
                {'inspect_source','inspect_dependencies'} for e in events),
            'tool_results':sum(e.get('kind')=='tool_result' for e in events),
            'recorded_error_events':[e for e in events if e.get('kind')=='error'],
            'termination_reason':trace['state'].get('termination_reason'),
            'remaining_budget':trace['state'].get('budget'),
            'correction_history_entries':len(trace['state'].get('revisions',[])),
            'billing_cost':None,
            'usage_limit':'Null/missing usage is unknown, not zero; sums cover reported fields only.'}


def compare_saved(partition_path='results/dependency_baseline/petclinic_k5.json',
                  trace_path='results/groq_live/langgraph_pilot_1.json'):
    partition_path, trace_path = inside(Path(partition_path)), inside(Path(trace_path))
    package = analyze(ROOT/'sample_petclinic')
    partition = json.loads(partition_path.read_text(encoding='utf-8'))
    trace = json.loads(trace_path.read_text(encoding='utf-8'))
    fingerprint = package['snapshot']['eligible_java_files_sha256']
    if partition['snapshot']['eligible_java_files_sha256'] != fingerprint or \
       trace['provenance']['source_snapshot']['eligible_java_files_sha256'] != fingerprint:
        raise ValueError('Source fingerprint mismatch; inputs are not comparable')
    raw_path = ROOT/'results/dependency_baseline/petclinic_raw.json'
    raw_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if partition['raw_analyzer_sha256'] != raw_hash or trace['provenance']['dependency_json_sha256'] != raw_hash:
        raise ValueError('Dependency fingerprint mismatch')
    package_rows = group_rows(package['candidate_services'],source_paths=True)
    universe = {r['class'] for r in package_rows}
    if set(partition['nodes']) != universe or not set(SCOPE)<=universe:
        raise ValueError('Source and saved graph class inventories differ')
    if sorted(trace['state']['scope']) != SCOPE:
        raise ValueError('Saved trace must use the exact three-class pilot scope')
    methods = {
        'package':summarize_assignments(package_rows,SCOPE,universe),
        'dependency_saved_full_graph':summarize_assignments(group_rows(partition['graph_groups']),SCOPE,universe),
        'tracemicro_saved_live':summarize_assignments(trace['state']['candidate_assignments'],SCOPE,universe)}
    methods['package']['original_group_count'] = len(package['candidate_services'])
    methods['dependency_saved_full_graph']['original_group_count'] = len(partition['graph_groups'])
    methods['tracemicro_saved_live']['allowed_service_labels'] = trace['state']['services']
    methods['tracemicro_saved_live']['recorded_verification_findings'] = trace['state']['verification_findings']
    return {'experiment':'PetClinic three-class offline development comparison',
            'scope':SCOPE, 'eligible_full_snapshot_class_count':len(universe),
            'source_fingerprint':fingerprint, 'upstream_commit':None,
            'dependency_json_sha256':raw_hash,
            'saved_inputs':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in [partition_path,trace_path]},
            'methods':methods, 'recorded_live_resources':recorded_resources(trace),
            'architectural_quality_evaluated':False,
            'limitations':['No reclustering: existing full-graph partition is only restricted.',
                'Package grouping recomputed on the unchanged full snapshot, then restricted.',
                'Shared multi-service rows and original evidence IDs are preserved.',
                'Coverage and record presence do not establish valid or correct architecture.',
                'Group counts/labels differ; this is not a controlled quality comparison.',
                'No independent reference, F1, weighted similarity or research-gap evaluation.',
                'Trace usage is historical live usage, not comparison-program resource usage.',
                'JPetStore and AcmeAir are not read or used.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,help='New workspace-local JSON path')
    args = parser.parse_args()
    target = inside(Path(args.output))
    if target.exists():
        parser.error('Refusing to overwrite comparison output')
    result = compare_saved()
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
    print(json.dumps({name:{k:method[k] for k in ['assignment_coverage','missing_class_records',
        'duplicate_class_records','unknown_classes_in_input','represented_group_count']}
        for name,method in result['methods'].items()},indent=2))
    print('Saved offline development comparison:',args.output)


if __name__=='__main__': main()
