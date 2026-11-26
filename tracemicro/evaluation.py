"""Offline metrics against explicit human annotations; no built-in reference labels."""
import itertools


def metrics(truth, predicted):
    tp, fp, fn = len(truth & predicted), len(predicted-truth), len(truth-predicted)
    return {'tp': tp, 'fp': fp, 'fn': fn,
            'precision': tp/(tp+fp) if tp+fp else None,
            'recall': tp/(tp+fn) if tp+fn else None,
            'f1': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None}


def memberships(rows, universe, *, reference=False):
    result = {}
    for row in rows:
        name, labels = row['class'], row['services']
        if name not in universe or name in result:
            raise ValueError('Unknown or duplicate class')
        if not isinstance(labels, list) or any(not isinstance(s, str) or not s.strip() for s in labels) or len(set(labels)) != len(labels):
            raise ValueError('Invalid service labels')
        if reference:
            decision = row['decision']
            if decision not in ('domain', 'shared', 'infrastructure', 'uncertain', 'exclude'):
                raise ValueError('Reference decision missing or invalid')
            if (decision == 'domain' and len(labels) != 1) or (decision == 'shared' and len(labels) < 2):
                raise ValueError('Reference membership contradicts decision')
        elif not labels or type(row.get('shared')) is not bool or row['shared'] != (len(labels) > 1):
            raise ValueError('Prediction membership contradicts sharing')
        result[name] = row
    if reference and set(result) != set(universe):
        raise ValueError('Reference must explicitly decide every eligible class')
    return result


def evaluate(reference, predicted, universe):
    reference = memberships(reference, universe, reference=True)
    predicted = memberships(predicted, universe)
    scored = {name for name, row in reference.items() if row['decision'] not in ('exclude', 'uncertain')}
    domain = {name for name in scored if reference[name]['decision'] == 'domain'}
    shared = {name for name in scored if reference[name]['decision'] == 'shared'}
    predicted_shared = {name for name in scored & predicted.keys() if predicted[name]['shared']}
    def together(rows, a, b):
        return a in rows and b in rows and bool(set(rows[a]['services']) & set(rows[b]['services']))
    candidates = list(itertools.combinations(sorted(domain), 2))
    truth_pairs = {pair for pair in candidates if together(reference, *pair)}
    predicted_pairs = {pair for pair in candidates if together(predicted, *pair)
                       and not predicted[pair[0]]['shared'] and not predicted[pair[1]]['shared']}
    truth_associations = {(s, d) for s in shared for d in domain if together(reference, s, d)}
    predicted_associations = {(s, d) for s in predicted_shared for d in domain if s != d
        and d in predicted and not predicted[d]['shared'] and together(predicted, s, d)}
    return {'eligible_classes': len(universe), 'scored_classes': len(scored),
            'uncertain': sorted(name for name, row in reference.items() if row['decision'] == 'uncertain'),
            'excluded': sorted(name for name, row in reference.items() if row['decision'] == 'exclude'),
            'missing_predictions': sorted(scored-predicted.keys()),
            'coverage': len(scored & predicted.keys())/len(scored) if scored else None,
            'domain_pairs': metrics(truth_pairs, predicted_pairs),
            'shared_identification': metrics(shared, predicted_shared),
            'shared_domain_anchor_associations': metrics(truth_associations, predicted_associations),
            'limitations': 'Pair metrics use reference domain classes only. Missing predictions create no positive links. '
                'Shared associations use shared-class/domain-class anchors, ignoring service label spelling. '
                'Groups with no domain anchors cannot be assessed by association pairs. Infrastructure contributes to coverage and shared detection, not domain pair quality. '
                'Zero-denominator metrics are null; no perfect score is inferred.'}
