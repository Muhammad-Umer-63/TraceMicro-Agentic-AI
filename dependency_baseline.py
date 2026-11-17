"""Deterministic graph baseline over the official analyzer JSON; no Java extraction."""
import argparse
import hashlib
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path

from baseline import analyze

DIRECT_TYPES = {'EXTENDS', 'IMPLEMENTS', 'CALLS', 'USES', 'REFERENCES', 'INJECTS',
                'ASSOCIATES', 'ANNOTATED_WITH', 'CREATES', 'PERSISTS', 'DEPENDS_ON'}
INVERSE_TYPES = {'EXTENDED_BY', 'IMPLEMENTED_BY', 'CALLED_BY', 'USED_BY', 'REFERENCED_BY',
                 'INJECTED_BY', 'ASSOCIATED_WITH', 'ANNOTATES', 'CREATED_BY', 'PERSISTED_BY', 'DEPENDENCY_OF'}


def load_graph(data):
    """Keep direct typed edges only; inverse exports are not new dependencies."""
    classes = data.get('classes')
    if not isinstance(classes, dict) or not classes:
        raise ValueError('Expected nonempty analyzer classes object')
    nodes = sorted(classes)
    edges = []
    for source in nodes:
        for kind, targets in classes[source].get('relationships', {}).items():
            if kind in INVERSE_TYPES:
                continue
            if kind not in DIRECT_TYPES:
                raise ValueError('Unknown relationship type: '+kind)
            if not isinstance(targets, dict):
                raise ValueError('Expected target/count object')
            for target, count in sorted(targets.items()):
                if target not in classes or source == target:
                    raise ValueError('Invalid internal edge: '+source+' -> '+target)
                if type(count) is not int or count <= 0:
                    raise ValueError('Relationship count must be a positive integer')
                edges.append({'source': source, 'target': target, 'type': kind, 'occurrences': count})
    return nodes, sorted(edges, key=lambda e:(e['source'], e['target'], e['type']))


def cluster(nodes, edges, target_count):
    """Average-link agglomeration on simple undirected adjacency, lexical ties."""
    if len(set(nodes)) != len(nodes) or not 1 <= target_count <= len(nodes):
        raise ValueError('Require unique nodes and 1 <= target_count <= node count')
    links = {frozenset((e['source'], e['target'])) for e in edges}
    groups = [(n,) for n in sorted(nodes)]
    history = []
    while len(groups) > target_count:
        options = []
        for i, left in enumerate(groups):
            for j in range(i+1, len(groups)):
                right = groups[j]
                cross = sum(frozenset((a,b)) in links for a in left for b in right)
                score = Fraction(cross, len(left)*len(right))
                options.append((-score, left, right, i, j))
        neg_score, left, right, i, j = min(options)
        history.append({'left': list(left), 'right': list(right),
                        'score_numerator': (-neg_score).numerator,
                        'score_denominator': (-neg_score).denominator,
                        'zero_link_merge': neg_score == 0})
        groups = sorted([g for index,g in enumerate(groups) if index not in {i,j}]
                        + [tuple(sorted(left+right))])
    return {'group_'+str(i+1): list(g) for i,g in enumerate(groups)}, history


def structural_counts(nodes, edges, groups):
    memberships = [n for members in groups.values() for n in members]
    if sorted(memberships) != sorted(nodes):
        raise ValueError('Grouping must assign every node exactly once')
    lookup = {n:g for g,members in groups.items() for n in members}
    directed = {(e['source'], e['target']) for e in edges}
    undirected = {frozenset(pair) for pair in directed}
    cross = sum(lookup[a] != lookup[b] for a,b in directed)
    adjacency = {n:set() for n in nodes}
    for a,b in directed:
        adjacency[a].add(b)
        adjacency[b].add(a)
    unseen, components = set(nodes), []
    while unseen:
        stack, component = [min(unseen)], set()
        while stack:
            n = stack.pop()
            if n in component:
                continue
            component.add(n)
            stack.extend(sorted(adjacency[n]-component))
        unseen -= component
        components.append(sorted(component))
    return {'node_count':len(nodes), 'typed_direct_edge_count':len(edges),
            'unique_directed_pair_count':len(directed), 'unique_undirected_pair_count':len(undirected),
            'analyzer_reported_occurrences':sum(e['occurrences'] for e in edges),
            'group_count':len(groups), 'group_sizes':sorted(map(len,groups.values()), reverse=True),
            'cross_group_directed_pairs':cross, 'within_group_directed_pairs':len(directed)-cross,
            'cross_group_directed_pair_ratio':cross/len(directed) if directed else None,
            'isolated_nodes':sorted(n for n in nodes if not adjacency[n]),
            'weak_components':components}


def compare(raw_path, repository, target_count):
    raw_path = Path(raw_path)
    raw = json.loads(raw_path.read_text(encoding='utf-8'))
    nodes, edges = load_graph(raw)
    grouped, history = cluster(nodes, edges, target_count)
    package = analyze(repository)
    # Diagnostic filename/package mapping only, never a replacement extractor.
    package_groups = {name:sorted(name+'.'+Path(p).stem for p in files)
                      for name,files in package['candidate_services'].items()}
    expected = {n for names in package_groups.values() for n in names}
    missing, extra = sorted(expected-set(nodes)), sorted(set(nodes)-expected)
    package_stats = None if missing or extra else structural_counts(nodes, edges, package_groups)
    table = [{ 'class':n, 'graph_group':next(g for g,m in grouped.items() if n in m),
               'package_group':next((g for g,m in package_groups.items() if n in m),None)} for n in nodes]
    return {'baseline':'official static dependency graph / deterministic average-link clustering',
            'algorithm':'Maximum cross-edge density |E(A,B)|/(|A|*|B|); simple undirected links; lexical tuple tie-break; merge to exact k, including zero-link merges.',
            'target_service_count':target_count,
            'target_count_status':'Experimental setting, not validated reference truth',
            'raw_analyzer_sha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            'snapshot':package['snapshot'], 'nodes':nodes, 'direct_typed_edges':edges,
            'graph_groups':grouped, 'package_groups':package_groups, 'merge_history':history,
            'graph_structure':structural_counts(nodes, edges, grouped), 'package_structure':package_stats,
            'membership_comparison':table,
            'coverage':{'eligible_source_files':len(package['source_inventory']),
                        'source_identity_mapping':'package declaration plus filename stem; not compiler type resolution',
                        'missing_filename_identifiers':missing, 'extra_analyzer_identifiers':extra,
                        'reported_classes':raw.get('metadata',{}).get('totalClasses'),
                        'parse_failure_count':None, 'unresolved_reference_count':None},
            'limitations':['Static heuristic dependencies, not runtime calls or behavioral correctness.',
                           'Original analyzer does not provide complete parse/resolution diagnostics.',
                           'Occurrences reflect analyzer traversal and are not runtime frequencies.',
                           'All types/occurrence weights collapsed for clustering; no shared-class assignments.',
                           'No reference labels or architectural accuracy scoring used.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analyzer_json')
    parser.add_argument('repository')
    parser.add_argument('--services', type=int, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = compare(args.analyzer_json, args.repository, args.services)
    out = Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['coverage','graph_structure','package_structure']},indent=2))
