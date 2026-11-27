"""Recompute PetClinic comparisons offline from frozen inputs and saved outputs."""
import argparse
from collections import Counter
import csv
from hashlib import sha256
from html import escape
from itertools import combinations
import json
from pathlib import PureWindowsPath
from statistics import mean, stdev

from dependency_baseline import compare
from petclinic_batch_prototype import TOOLS
from petclinic_full_scope_review import dependency_diagnostics, groups, membership_signatures, pairs
from petclinic_final_day_cap2048 import SESSION as FRESH_SESSION
from petclinic_final_day_continue import CAP_MANIFEST, verify_manifest
from petclinic_final_day_live import RESULTS
from petclinic_global_plan import CAP2048_VERSION, EXPERIMENTS, VERSION
from tracemicro.pilot import ROOT, inside
from tracemicro.workflow import validate_output


ORIGINALS = ('original_1', 'original_2', 'original_3')
PLANNING = ('planner_v1', 'compact_v2')
PENDING = {'prepared', 'planned', 'in_progress'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows, fields):
    with path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def group_diagnostics(rows, scope, typed, directed):
    grouped = groups(rows)
    return {
        'assigned': len(rows), 'eligible': len(scope), 'group_count': len(grouped),
        'sizes': sorted(map(len, grouped.values()), reverse=True),
        'shared_classes': sorted(row['class'] for row in rows if row['shared']),
        'groups': grouped,
        'crossing': {name: dependency_diagnostics(rows, edges) for name, edges in
                     [('typed_records', typed), ('directed_pairs', directed)]},
    }


def resource_row(summary):
    reported = summary['reported_tokens']
    missing = summary['records_missing_token_fields']
    return {
        'attempts': summary['global_transport_attempts'],
        'known_input_tokens': reported['prompt_tokens'],
        'known_output_tokens': reported['completion_tokens'],
        'known_total_tokens': reported['total_tokens'],
        'records_missing_input': missing['prompt_tokens'],
        'records_missing_output': missing['completion_tokens'],
        'records_missing_total': missing['total_tokens'],
        'pacing_seconds': summary.get('global_wait_seconds', summary.get('wait_seconds')),
        'elapsed_seconds': summary.get('total_elapsed_seconds', summary.get('elapsed_seconds')),
    }


def planning_diagnostics(folder):
    path = folder / 'planning.json'
    if not path.exists():
        return None
    plan = read(path)
    records = plan['model_usage']
    record = records[-1] if records else {}
    error = record.get('provider_error', {})
    return {
        'status': plan['status'], 'output': plan.get('output'),
        'findings': plan.get('findings', []), 'http_status': plan.get('http_status'),
        'error_code': plan.get('error_code'), 'provider_code': error.get('code'),
        'finish_reason': record.get('finish_reason'),
        'response_json_received': record.get('response_json_received'),
        'action_json_received': record.get('action_json_received'),
        'usage': record.get('usage'),
        'input_bytes': record.get('input_bytes'),
        'rejected_generation': error.get('rejected_generation_structure'),
    }


def inspect_run(folder, summary, scope, frozen):
    path = folder / 'summary.json'
    if summary['source_fingerprint'] != frozen['source_fingerprint'] or (
        summary['dependency_json_sha256'] != frozen['dependency_json_sha256']
    ):
        raise ValueError(f'Input mismatch in {folder.name}')
    prep = read(folder / 'precollection.json')
    rows = summary['accepted_assignments']
    findings = validate_output({'assignments': rows}, scope,
                               summary['allowed_service_labels'], prep['evidence'], TOOLS)
    if findings != summary['combined_findings']:
        raise ValueError(f'Saved and replayed validation disagree in {folder.name}')
    if summary['status'] == 'basic_checks_passed' and findings:
        raise ValueError(f'Completed output failed replay in {folder.name}')
    accepted, batch_requests = [], []
    for trace_path in sorted(folder.glob('batch_??.json')):
        trace = read(trace_path)
        state = trace['state']
        for record in trace['model_usage']:
            fields = ('status', 'http_status', 'error_code', 'finish_reason', 'response_json_received',
                      'action_json_received', 'usage', 'input_bytes', 'provider_error')
            batch_requests.append({'batch': trace_path.stem, **{key: record.get(key) for key in fields}})
        if state['termination_reason'] == 'basic_checks_passed':
            batch_rows = state['candidate_assignments']
            if validate_output({'assignments': batch_rows}, state['scope'], state['services'],
                               state['evidence'], TOOLS):
                raise ValueError(f'Saved batch failed validation in {trace_path}')
            accepted.extend(batch_rows)
    if accepted != rows:
        raise ValueError(f'Saved batches and accepted output disagree in {folder.name}')
    return rows, {
        'status': summary['status'], 'resources': resource_row(summary),
        'finding_counts': dict(Counter(row['code'] for row in findings)),
        'planning': planning_diagnostics(folder),
        'batch_requests': batch_requests,
        'batches': [{key: batch[key] for key in ('batch', 'stop', 'findings', 'errors', 'error_type')
                     if key in batch} for batch in summary['batches']],
        'artifact': path.relative_to(ROOT).as_posix(), 'summary_sha256': digest(path),
    }


def agreement(complete):
    reports = []
    for (left, a), (right, b) in combinations(complete.items(), 2):
        ma, mb = membership_signatures(a), membership_signatures(b)
        pa, pb = pairs(a), pairs(b)
        reports.append({
            'left': left, 'right': right, 'classes_compared': len(ma.keys() & mb.keys()),
            'same_neighborhood': sum(ma[name] == mb[name] for name in ma.keys() & mb.keys()),
            'coassigned_pairs_left': len(pa), 'coassigned_pairs_right': len(pb),
            'coassigned_pair_intersection': len(pa & pb), 'coassigned_pair_union': len(pa | pb),
        })
    return reports


def group_figure(path, entries):
    labels = {name: f'Original model {i}' for i, name in enumerate(ORIGINALS, 1)}
    labels.update(package='Package baseline', dependency='Dependency baseline')
    height = 110 + 34 * len(entries)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" viewBox="0 0 760 {height}">',
             '<title>PetClinic nonempty group sizes</title>',
             '<desc>Group sizes for completed methods, sorted within each row. Shared classes count in each group.</desc>',
             f'<rect width="760" height="{height}" fill="#ffffff"/>',
             '<g font-family="sans-serif" font-size="13" fill="#152439">',
             '<text x="16" y="24" font-size="18" font-weight="bold">PetClinic nonempty group sizes</text>']
    upper = 5 * max((sum(row['sizes']) + 4) // 5 for row in entries)
    scale = 500 / upper
    for tick in range(0, upper + 1, 5):
        x = 182 + scale * tick
        lines.append(f'<path d="M{x},49 V{height-45}" stroke="#dce4ee"/>')
        lines.append(f'<text x="{x}" y="{height-26}" text-anchor="middle">{tick}</text>')
    colors = ('#244c75', '#147a79', '#8b5a16', '#7a4d87', '#4d5d69')
    for index, entry in enumerate(entries):
        y = 55 + 34 * index
        name = entry['method']
        label = labels.get(name, name.replace('compact_v3_', 'Compact v3 '))
        lines.append(f'<text x="16" y="{y+15}">{escape(label)}</text>')
        x = 182
        for size, color in zip(entry['sizes'], colors):
            width = scale * size
            lines.append(f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="22" fill="{color}" stroke="white"/>')
            lines.append(f'<text x="{x+width/2:.2f}" y="{y+15}" text-anchor="middle" fill="white">{size}</text>')
            x += width
    lines.extend([f'<text x="432" y="{height-6}" text-anchor="middle">Class memberships</text>', '</g></svg>'])
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def review(output, historical_only=False):
    frozen = verify_manifest(RESULTS / 'frozen_inputs.json', {
        'petclinic_global_plan.py': RESULTS / 'frozen_v3/petclinic_global_plan.py',
    })
    archive = RESULTS / 'saved'
    for name, record in read(archive / 'manifest.json').items():
        if digest(archive / name) != record['sha256']:
            raise ValueError(f'Archived artifact changed: {name}')

    graph = compare(ROOT / 'results/dependency_baseline/petclinic_raw.json',
                    ROOT / 'sample_petclinic', 5)
    scope, typed = graph['nodes'], graph['direct_typed_edges']
    directed = [{'source': a, 'target': b} for a, b in sorted({(e['source'], e['target']) for e in typed})]
    if (len(scope), len(typed), len(directed)) != (25, 59, 42) or (
        graph['snapshot']['eligible_java_files_sha256'] != frozen['source_fingerprint']
    ) or graph['coverage']['missing_filename_identifiers'] or graph['coverage']['extra_analyzer_identifiers']:
        raise ValueError('Frozen class universe or graph differs')

    entries, assignments, complete, supplemental = [], {}, {}, []
    for method, mapping in [('package', graph['package_groups']), ('dependency', graph['graph_groups'])]:
        rows = [{'class': name, 'services': [label], 'shared': False}
                for label, members in mapping.items() for name in members]
        entries.append({'method': method, 'kind': 'deterministic_recomputation',
                        'status': 'complete', 'resources': {'attempts': 0}, 'finding_counts': {},
                        **group_diagnostics(rows, scope, typed, directed)})
        assignments[method] = complete[method] = rows

    session_dirs = [] if historical_only else [RESULTS / 'live_v3', FRESH_SESSION]
    live_dirs = [folder for session in session_dirs for folder in sorted(session.glob('run_*'))]
    variant = verify_manifest(CAP_MANIFEST) if any(
        folder.name.endswith('_cap2048') for folder in live_dirs
    ) else None
    pending = []
    sources = [(name, archive / name) for name in ORIGINALS + PLANNING + ('synthetic_v3',)]
    sources.extend((f'compact_v3_{folder.name}' if folder.parent != FRESH_SESSION
                    else f'compact_v3_fresh_{folder.name}', folder) for folder in live_dirs)
    for method, folder in sources:
        path = folder / 'summary.json'
        current = method.startswith('compact_v3_')
        try:
            summary = read(path)
        except (FileNotFoundError, json.JSONDecodeError):
            if not current:
                raise
            pending.append(method)
            continue
        if current and summary['status'] in PENDING:
            pending.append(method)
            continue
        if current:
            version, condition = ((CAP2048_VERSION, variant) if folder.name.endswith('_cap2048')
                                  else (VERSION, frozen))
            hashes = condition['files']
            if (summary['version'] != version or
                summary['experiment_sha256'] != hashes[f'configs/{EXPERIMENTS[version]}'] or
                any(hashes[PureWindowsPath(name).as_posix()] != value
                    for name, value in summary['code_sha256'].items())):
                raise ValueError(f'Changed current condition in {folder.name}')
        expected_kind = 'groq_simulated_http' if method == 'synthetic_v3' else 'groq_live'
        if summary['run_kind'] != expected_kind:
            raise ValueError(f'Unexpected run kind in {folder.name}')
        rows, inspection = inspect_run(folder, summary, scope, frozen)
        row = {'method': method, 'kind': expected_kind, **inspection,
               **group_diagnostics(rows, scope, typed, directed)}
        if method == 'synthetic_v3':
            supplemental.append(row)
            continue
        entries.append(row)
        assignments[method] = rows
        if summary['status'] == 'basic_checks_passed':
            complete[method] = rows

    probe_path = archive / 'reduced_probe/probe.json'
    probe = read(probe_path)
    supplemental.append({
        'method': 'reduced_probe', 'kind': probe['run_kind'], 'status': probe['status'],
        'resources': resource_row(probe), 'plan': probe['output'],
        'assignment_stage': False, 'artifact': probe_path.relative_to(ROOT).as_posix(),
    })
    original_resources = [row['resources'] for row in entries if row['method'] in ORIGINALS]
    tokens = [row['known_total_tokens'] for row in original_resources]
    elapsed = [row['elapsed_seconds'] for row in original_resources]
    sessions = {}
    for folder in session_dirs:
        ledger_path = folder / 'session_budget.json'
        if not ledger_path.is_file():
            continue
        ledger = read(ledger_path)
        prefix = folder.relative_to(ROOT).as_posix() + '/'
        terminal_requests = sum(row['resources']['attempts'] for row in entries
                                if row.get('artifact', '').startswith(prefix))
        sessions[folder.name] = {
            'charged_attempts': ledger['requests'], 'attempts_in_terminal_summaries': terminal_requests,
            'charged_attempts_outside_terminal_summaries': ledger['requests'] - terminal_requests,
            'requested_pacing_seconds': ledger['wait_total'],
        }
    result = {'eligible_classes': scope, 'typed_records': len(typed), 'directed_pairs': len(directed),
              'quality_scores': None, 'current_pending_or_interrupted': pending,
              'current_sessions': sessions,
              'original_runs_aggregate': {
                  'attempts': sum(row['attempts'] for row in original_resources),
                  'known_total_tokens': sum(tokens), 'tokens_mean': mean(tokens),
                  'tokens_sample_sd': stdev(tokens), 'elapsed_mean_seconds': mean(elapsed),
                  'elapsed_sample_sd_seconds': stdev(elapsed),
              },
              'comparison': entries, 'supplemental': supplemental, 'membership_agreement': agreement(complete)}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    flat = []
    resources = []
    for row in entries:
        counts = {f'{prefix}_{label}': diagnostics[key]
                  for prefix, diagnostics in row['crossing'].items()
                  for label, key in [('covered', 'typed_edges_with_both_classes_assigned'),
                                     ('crossing', 'typed_edges_without_common_service')]}
        plan = row.get('planning') or {}
        plan_services = (plan.get('output') or {}).get('services', [])
        flat.append({**row, **counts, 'shared': len(row['shared_classes']),
                     'planning_status': plan.get('status'),
                     'proposed_services': len(plan_services) if plan else None})
    for row in entries + supplemental:
        plan = row.get('planning') or {}
        diagnostic = plan
        failure_stage = 'planning' if row['status'] == 'failed_plan' else None
        if row['status'] == 'failed_batch':
            failure_stage = 'assignment'
            batch_requests = row['batch_requests']
            diagnostic = batch_requests[-1] if batch_requests else {}
        provider_error = diagnostic.get('provider_error') or {}
        resources.append({**row, **row['resources'], 'failure_stage': failure_stage,
                          'http_status': diagnostic.get('http_status'),
                          'provider_code': diagnostic.get('provider_code') or provider_error.get('code'),
                          'error_code': diagnostic.get('error_code'),
                          'finish_reason': diagnostic.get('finish_reason')})
    write_csv(output / 'comparison.csv', flat, ['method', 'kind', 'status', 'assigned', 'eligible',
              'planning_status', 'proposed_services', 'sizes', 'shared', 'typed_records_covered', 'typed_records_crossing',
              'directed_pairs_covered', 'directed_pairs_crossing', 'finding_counts'])
    write_csv(output / 'resources.csv', resources, ['method', 'kind', 'status', *resource_row(probe),
              'failure_stage', 'http_status', 'provider_code', 'error_code', 'finish_reason', 'artifact'])
    lookup = {method: {row['class']: '|'.join(row['services']) for row in rows}
              for method, rows in assignments.items()}
    write_csv(output / 'memberships.csv',
              [{'class': name, **{method: members.get(name) for method, members in lookup.items()}}
               for name in scope], ['class', *lookup])
    group_figure(output / 'group_sizes.svg', [row for row in entries if row['method'] in complete])
    print(f'{len(scope)} classes, {len(typed)} typed records, {len(directed)} directed pairs')
    print(f'{len(complete)} complete conditions/runs, {len(entries) - len(complete)} saved full-scope failures, '
          f'{len(live_dirs) - len(pending)} terminal final-day attempts, {len(pending)} pending/interrupted')
    print(f'Wrote {output.relative_to(ROOT)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--historical-only', action='store_true', help='Use the frozen historical evidence only')
    arguments = parser.parse_args()
    review(inside(arguments.output_dir), arguments.historical_only)
