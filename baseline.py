"""Reproducible package baseline. Python 3.10+; no external dependencies."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def analyze(repository):
    root = Path(repository).resolve()
    source = root / 'src' / 'main' / 'java'
    if not source.is_dir():
        raise ValueError(f'Java source folder not found: {source}')
    groups, unassigned, inventory, records = {}, [], [], []
    # Ignore comments and literals so strings containing "package ...;" do not match.
    noise = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*[\s\S]*?\*/|//[^\n]*')
    for path in sorted(source.rglob('*.java')):
        if path.name in {'package-info.java', 'module-info.java'}:
            continue
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        clean = noise.sub(' ', raw.decode('utf-8-sig', errors='replace'))
        match = re.search(r'\bpackage\s+([\w.]+)\s*;', clean)
        inventory.append(relative)
        records.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest()})
        if match:
            groups.setdefault(match.group(1), []).append(relative)
        else:
            unassigned.append(relative)
    if not inventory:
        raise ValueError('No eligible Java files found.')
    canonical = json.dumps(records, sort_keys=True, separators=(',', ':')).encode()
    assigned = sum(map(len, groups.values()))
    return {
        'baseline': 'package-based grouping',
        'unit': 'Java source file',
        'state': {
            'status': 'completed', 'files_discovered': len(inventory),
            'files_assigned': assigned, 'assignment_coverage': assigned / len(inventory),
            'candidate_service_count': len(groups), 'unassigned_files': unassigned,
        },
        'source_inventory': inventory, 'candidate_services': groups,
        'snapshot': {
            'upstream_commit': None,
            'provenance': 'User-supplied ZIP snapshot; upstream commit not established.',
            'eligible_java_files_sha256': hashlib.sha256(canonical).hexdigest(),
            'fingerprint_scope': 'Eligible production Java files only, not whole repository.',
            'files': records,
        },
        'limitations': [
            'Package groups are preliminary candidates, not validated business services.',
            'One Java source file is the unit; nested/multiple types are not resolved.',
            'Files without a package declaration are reported as unassigned.',
            'No dependency, runtime, database, model or agent analysis.',
            'Assignment coverage does not measure decomposition correctness.',
        ],
    }


def compare_archived(current, archived):
    """Compare all original measured quantities and actual membership lists."""
    def groups(value):
        return {key: sorted(paths) for key, paths in value.items()}
    def state(value):
        value = dict(value)
        if 'unassigned_files' in value:
            value['unassigned_files'] = sorted(value['unassigned_files'])
        return value
    # Filesystem traversal ordering can differ on Windows and Linux.
    # Sorting lists preserves duplicate detection while ignoring incidental order.
    return {
        'state': state(current['state']) == state(archived.get('state') or {}),
        'source_inventory': sorted(current['source_inventory']) == sorted(archived.get('source_inventory', [])),
        'candidate_services': groups(current['candidate_services']) == groups(archived.get('candidate_services', {})),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository')
    parser.add_argument('--output', default='results/baseline_result.json')
    parser.add_argument('--compare', help='Original baseline JSON to reproduce')
    args = parser.parse_args()
    try:
        result = analyze(args.repository)
        if args.compare:
            archived = json.loads(Path(args.compare).read_text(encoding='utf-8'))
            result['archive_comparison'] = compare_archived(result, archived)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result['state'], indent=2))
        if args.compare:
            print('Archive comparison:', result['archive_comparison'])
            if not all(result['archive_comparison'].values()):
                raise SystemExit('Original result was not reproduced; inspect input differences.')
        print(f'Saved: {output}')
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
