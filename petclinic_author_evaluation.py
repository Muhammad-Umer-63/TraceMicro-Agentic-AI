"""Score complete PetClinic outputs against the frozen author development reference."""
import argparse
from collections import Counter
import csv
import json
import sys

from annotation_evaluate import reference_metadata
from petclinic_comparison import group_rows
from petclinic_final_day_review import ORIGINALS, RESULTS, digest, read, review, write_csv
from petclinic_full_scope_review import groups
from tracemicro.evaluation import evaluate, memberships
from tracemicro.pilot import ROOT, inside


REFERENCE = RESULTS / 'author_evaluation_20261127'
METRICS = ('domain_pairs', 'shared_identification', 'shared_domain_anchor_associations')


def load_reference(scope):
    receipt = read(REFERENCE / 'reference_receipt.json')
    path = REFERENCE / receipt['reference']
    if digest(path) != receipt['sha256']:
        raise ValueError('Frozen reference hash does not match the approval receipt')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream, strict=True))
    for row in rows:
        if not row['rationale'].strip() or not row['evidence'].strip():
            raise ValueError('Reference decisions require rationale and evidence')
        row['services'] = row['services'].split('|') if row['services'] else []
    memberships(rows, set(scope), reference=True)
    return rows, receipt


def reliability_rows(structural):
    with (ROOT / 'docs/EXPERIMENT_REGISTER.csv').open(encoding='utf-8-sig', newline='') as stream:
        registered = [row for row in csv.DictReader(stream) if row['execution'] in ('live', 'groq_live')]
    rows = []
    for entry in registered:
        path = inside(entry['trace_path'])
        if digest(path) != entry['artifact_sha256']:
            raise ValueError(f'Registered live artifact changed: {entry["trace_path"]}')
        scope = int(entry['scope_count'])
        rows.append({
            'condition': entry['condition'], 'scope_kind': 'full' if scope == 25 else 'limited',
            'scope_classes': scope, 'status': entry['status'], 'accepted_classes': entry['accepted_classes'],
            'requests': entry['real_transport_requests'], 'known_tokens': entry['known_total_tokens'],
            'requests_without_total_usage': entry['requests_without_total_usage'],
            'pacing_seconds': entry['pacing_seconds'], 'elapsed_seconds': entry['elapsed_seconds'],
            'diagnostic': entry['validation_or_failure'], 'artifact': path.relative_to(ROOT).as_posix(),
            'sha256': entry['artifact_sha256'],
        })
    recorded = {row['artifact'] for row in rows}
    for entry in structural['comparison'] + structural['supplemental']:
        path = entry.get('artifact', '')
        final_day = path.startswith(RESULTS.relative_to(ROOT).as_posix() + '/live_')
        probe = entry['method'] == 'reduced_probe'
        if (not final_day and not probe) or path in recorded:
            continue
        resource = entry['resources']
        rows.append({
            'condition': entry['method'], 'scope_kind': 'planning diagnostic' if probe else 'full',
            'scope_classes': 1 if probe else 25, 'status': entry['status'],
            'accepted_classes': entry.get('assigned'), 'requests': resource['attempts'],
            'known_tokens': resource['known_total_tokens'],
            'requests_without_total_usage': resource['records_missing_total'],
            'pacing_seconds': resource['pacing_seconds'], 'elapsed_seconds': resource['elapsed_seconds'],
            'diagnostic': {'planning': entry.get('planning'), 'batches': entry.get('batches')},
            'artifact': path, 'sha256': digest(inside(path)),
        })
    return rows


def score(output):
    if output.exists():
        raise FileExistsError(output)
    review(output / 'structural')
    structural = read(output / 'structural/comparison.json')
    scope = structural['eligible_classes']
    reference, receipt = load_reference(scope)
    entries = {entry['method']: entry for entry in structural['comparison']}
    results = []
    for method in ('package', 'dependency', *ORIGINALS):
        entry = entries[method]
        if method in ORIGINALS:
            prediction = read(inside(entry['artifact']))['accepted_assignments']
        else:
            prediction = group_rows(entry['groups'])
        if (entry['status'] not in ('complete', 'basic_checks_passed') or len(prediction) != len(scope)
                or set(row['class'] for row in prediction) != set(scope) or groups(prediction) != entry['groups']):
            raise ValueError(f'Saved complete class assignments do not reconcile: {method}')
        results.append({'method': method, **evaluate(reference, prediction, scope)})
    metadata = {
        **reference_metadata('author-reviewed-development'),
        'chatgpt_assistance_disclosed': receipt['chatgpt_assistance_disclosed'],
        'reference_sha256': receipt['sha256'],
        'decisions': dict(Counter(row['decision'] for row in reference)),
    }
    (output / 'agreement.json').write_text(json.dumps(
        {'reference': metadata, 'results': results}, indent=2) + '\n', encoding='utf-8')
    flat = [{'method': row['method'], 'metric': metric, 'coverage': row['coverage'], **row[metric]}
            for row in results for metric in METRICS]
    write_csv(output / 'agreement.csv', flat, ['method', 'metric', 'coverage',
              'tp', 'fp', 'fn', 'precision', 'recall', 'f1'])
    reliability = reliability_rows(structural)
    write_csv(output / 'reliability.csv', reliability, ['scope_kind', 'scope_classes', 'condition',
              'status', 'accepted_classes', 'requests', 'known_tokens', 'requests_without_total_usage',
              'pacing_seconds', 'elapsed_seconds', 'diagnostic', 'artifact', 'sha256'])
    print(f'Scored {len(results)} complete outputs against {len(reference)} approved decisions')
    print(f'Exported {len(reliability)} live reliability/diagnostic records separately')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    arguments = parser.parse_args()

    def offline_guard(event, args):
        if event.startswith('socket.'):
            raise PermissionError('Author evaluation uses only saved artifacts')

    sys.addaudithook(offline_guard)
    score(inside(arguments.output_dir))
