"""Offline audit of saved full-scope runs and label-invariant membership agreement."""
import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path

from baseline import analyze
from petclinic_comparison import group_rows, summarize_assignments
from petclinic_batch_prototype import TOOLS
from tracemicro.pilot import ROOT, make_store
from tracemicro.workflow import validate_output


def groups(rows):
    result = {}
    for row in rows:
        for service in row['services']:
            result.setdefault(service, []).append(row['class'])
    return {key: sorted(value) for key, value in result.items()}


def membership_signatures(rows):
    """Preserve every shared membership while removing service-label spelling."""
    partition = groups(rows)
    return {row['class']: sorted([partition[label] for label in row['services']]) for row in rows}


def pairs(rows):
    return {pair for members in groups(rows).values() for pair in itertools.combinations(members, 2)}


def dependency_diagnostics(rows, edges):
    memberships = {row['class']: set(row['services']) for row in rows}
    covered = [edge for edge in edges if edge['source'] in memberships and edge['target'] in memberships]
    separated = [edge for edge in covered if not memberships[edge['source']] & memberships[edge['target']]]
    return {'typed_edges_total': len(edges), 'typed_edges_with_both_classes_assigned': len(covered),
            'typed_edges_without_common_service': len(separated),
            'ratio_over_covered_edges': len(separated)/len(covered) if covered else None,
            'definition': 'A directed typed static edge crosses when endpoints share no service. Shared memberships are sets. Missing endpoints excluded and counted separately; no runtime-frequency weighting.'}


def review(run_paths, output):
    output = (ROOT / output).resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    store = make_store()
    scope = store.classes
    package = analyze(ROOT / 'sample_petclinic')
    graph_path = ROOT / 'results/dependency_baseline/petclinic_k5.json'
    graph = json.loads(graph_path.read_text(encoding='utf-8'))
    if graph['snapshot']['eligible_java_files_sha256'] != store.snapshot['eligible_java_files_sha256']:
        raise ValueError('Baseline snapshot mismatch')
    methods = {'package': group_rows(package['candidate_services'], source_paths=True),
               'dependency': group_rows(graph['graph_groups'])}
    audits = []
    for run_path in run_paths:
        folder = (ROOT / run_path).resolve()
        folder.relative_to(ROOT)
        summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
        prep = json.loads((folder / 'precollection.json').read_text(encoding='utf-8'))
        if summary['source_fingerprint'] != store.snapshot['eligible_java_files_sha256'] or summary['dependency_json_sha256'] != store.graph_sha256:
            raise ValueError('Run input mismatch')
        rows = summary['accepted_assignments']
        findings = validate_output({'assignments': rows}, scope, summary['allowed_service_labels'], prep['evidence'], TOOLS)
        batches = []
        for trace_path in sorted(folder.glob('batch_??.json')):
            trace = json.loads(trace_path.read_text(encoding='utf-8'))
            decisions = [e for e in trace['events'] if e['kind'] == 'decision_requested']
            context = decisions[0].get('context', {}) if decisions else {}
            batches.append({'file': trace_path.name, 'verification_count': sum(e['kind'] == 'verification' for e in trace['events']),
                            'parsed_actions': sum(e['kind'] == 'decision_received' for e in trace['events']),
                            'termination': trace['state']['termination_reason'],
                            'findings': trace['state']['verification_findings'],
                            'rechecked_findings': validate_output({'assignments': trace['state']['candidate_assignments']},
                                trace['state']['scope'], trace['state']['services'], trace['state']['evidence'], TOOLS),
                            'previous_assignment_count': len(context.get('previous_accepted_assignments_for_global_label_consistency', [])),
                            'returned_models': sorted(set(r.get('returned_model', 'unknown') for r in trace['model_usage']))})
        name = str(folder.relative_to(ROOT))
        methods[name] = rows
        audits.append({'path': name, 'summary': summary, 'rechecked_findings': findings,
                       'batches': batches, 'partial_sources': [r for r in prep['ledger'] if r['source_excerpt_is_partial']],
                       'summary_sha256': hashlib.sha256((folder/'summary.json').read_bytes()).hexdigest()})
    agreement = []
    for left, right in itertools.combinations(methods, 2):
        a, b = membership_signatures(methods[left]), membership_signatures(methods[right])
        common = sorted(set(a) & set(b))
        equal = [name for name in common if a[name] == b[name]]
        pa, pb = pairs(methods[left]), pairs(methods[right])
        agreement.append({'left': left, 'right': right, 'common_classes': len(common),
                          'identical_membership_neighborhoods': equal,
                          'different_membership_neighborhoods': [name for name in common if name not in equal],
                          'coassigned_pairs_left': len(pa), 'coassigned_pairs_right': len(pb),
                          'coassigned_pair_intersection': len(pa & pb), 'coassigned_pair_union': len(pa | pb)})
    report = {'scope': scope, 'runs': audits, 'methods': {name: {'groups': groups(rows),
                  'dependency_diagnostics': dependency_diagnostics(rows, graph['direct_typed_edges']),
                  'coverage': summarize_assignments(rows, scope, scope)} for name, rows in methods.items()},
              'agreement': agreement, 'accuracy': None,
              'agreement_definition': 'Compare each class by the sorted member lists of ALL its associated groups. Label renames have no effect. Shared memberships remain separate. Pair agreement counts a pair once when it shares any service. These are agreement observations, without reference accuracy.'}
    (output/'review.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    with (output/'assignments.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['class'] + list(methods))
        for name in scope:
            writer.writerow([name] + ['|'.join(next((r['services'] for r in rows if r['class'] == name), [])) for rows in methods.values()])
    print(json.dumps({'runs': len(audits), 'classes': len(scope), 'output': str(output.relative_to(ROOT))}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='append', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    review(args.run, args.output_dir)
