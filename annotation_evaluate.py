"""Evaluate saved predictions against explicitly labelled human reference entry."""
import argparse
import csv
import json

from tracemicro.evaluation import evaluate
from tracemicro.pilot import make_store, inside


def reference_metadata(status):
    if status == 'author-reviewed-development':
        return {'reference_status': status,
                'reference_label': 'Author-reviewed development reference; reviewer has seen model outputs.',
                'reviewer_has_seen_model_outputs': True,
                'fulfills_two_independent_annotators': False}
    if status != 'adjudicated-human':
        raise ValueError('Unknown reference status')
    return {'reference_status': status, 'reference_label': 'User-declared adjudicated human reference',
            'fulfills_two_independent_annotators': None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--prediction', required=True)
    parser.add_argument('--reference-status', required=True, choices=['adjudicated-human', 'author-reviewed-development'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    with inside(args.reference).open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if not row.get('rationale', '').strip() or not row.get('evidence', '').strip():
            raise ValueError('Every reference decision needs human rationale and evidence')
        row['services'] = [s.strip() for s in row['services'].split('|') if s.strip()]
    prediction = json.loads(inside(args.prediction).read_text(encoding='utf-8'))
    assignments = prediction.get('accepted_assignments', prediction.get('state', {}).get('candidate_assignments'))
    if assignments is None:
        raise ValueError('No saved assignment output')
    result = evaluate(rows, assignments, make_store().classes)
    result.update(**reference_metadata(args.reference_status), prediction_status=prediction.get('status'),
                  reference=args.reference, prediction=args.prediction)
    out = inside(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('Saved reference assessment to', args.output)
