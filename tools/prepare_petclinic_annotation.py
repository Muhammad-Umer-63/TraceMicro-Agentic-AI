"""Create a neutral, blank two-reviewer package from fixed local evidence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from petclinic_batch_prototype import collect
from tracemicro.pilot import inside, make_store

GUIDE = """# Independent PetClinic annotation

This package contains eligible Java source, static relationships and blank sheets.
It contains no generated decomposition or reference answers. Reviewers should
receive ONLY this package, without the project results, baselines or discussions
of generated partitions. If already exposed, disclose that exposure in notes.

## Rubric

Read full source and relevant relationships. Describe a service as a business
responsibility with a clear data/interaction rationale. Assign arbitrary reviewer
service names consistently, using | between multiple memberships. Do not assume
package directories are the intended services. There is no required group count.

Choose one decision for every class.

- domain means one business-service membership, with exactly one service label.
- shared means at least two necessary service associations. Explain why sharing
  is appropriate and name all associations. Reuse alone is insufficient rationale.
- infrastructure means a cross-cutting technical/configuration class. Record any
  justified deployment service membership or leave services blank. If it genuinely
  requires multiple service memberships, use shared and explain infrastructure
  status in the rationale.
- uncertain means evidence does not support a confident decision. Describe what
  evidence is missing. It remains explicitly unscored until adjudicated.
- exclude means a justified scope exclusion. State the reason. Exclusions require
  adjudication and change the scored universe explicitly.

Confidence is high/medium/low. Every decision needs rationale and evidence such
as a full-source file and line range or typed edge from static_dependencies.json.
The E-ID index links the original bounded evidence records. Its source excerpts
are first 80 lines and sometimes partial; FULL eligible source is supplied here.
Static relationships can be incomplete and do not establish executed behavior.

## Independent procedure

1. Reviewer A and B each use a separate copy and their assigned blank sheet.
2. Do not see each other's decisions, model outputs or baseline partitions.
3. Review all 25 classes. Record ambiguities instead of inventing certainty.
4. Deliver the original sheet with reviewer identity/date and exposure notes.
5. Preserve each delivered file under a unique immutable filename. Compute its
   SHA256 with Get-FileHash and record it in a review receipt. Never overwrite it.
6. An adjudicator compares both files AFTER independent review. Populate the A/B
   columns in adjudication.csv verbatim and record final decisions/services,
   evidence and reasons for every disagreement. Keep the original two files.
7. The final class/decision/services/rationale/evidence columns form the reference.
   Do not score blank or unresolved references as human ground truth.

## Metric interpretation

The evaluator requires an explicit decision for every eligible class. Uncertain
and excluded rows are listed and removed from scored metrics. Infrastructure is
included in coverage/shared detection but excluded from domain pair F1. Domain
pair scoring uses reference-domain classes only. Missing model classes have no
positive pair links, penalizing true positive pairs that are missed. Model-shared
rows among reference-domain classes create no positive domain links. Shared
identification measures the class decision. Shared associations compare links
between shared classes and reference-domain anchor classes sharing a service,
so label renaming has no effect. Services with no domain anchors cannot be
assessed by that association measure. Zero denominators return null, never an
automatic perfect score. These metrics do not prove runtime correctness.

## Provenance limits

The eligible-source fingerprint is in manifest.json. Upstream commit/download date
are unknown. These 25 Java files form a source subset, not a runnable application.
Five package-info metadata files are outside the eligible universe and omitted.
No runtime traces or independently verified database schema are provided.
"""


def prepare(output):
    folder = inside(output)
    folder.mkdir(parents=True, exist_ok=False)
    store = make_store()
    evidence, ledger = collect(store)
    index, rows = {}, []
    for item in ledger:
        name = item['class']
        source = next(evidence[e] for e in item['evidence_ids'] if evidence[e]['tool'] == 'inspect_source')
        target = folder/'source'/Path(*name.split('.')).with_suffix('.java')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inside(source['path']), target)
        index[name] = {'source': str(target.relative_to(folder)), 'source_sha256': source['sha256'],
            'total_lines': item['source_total_lines'], 'original_evidence_ids': item['evidence_ids'],
            'original_excerpt_end_line': item['source_excerpt_end_line'],
            'original_excerpt_is_partial': item['source_excerpt_is_partial']}
        rows.append({'class': name, 'available_evidence': '|'.join(item['evidence_ids'])+'; '+str(target.relative_to(folder))})
    headers = ['class', 'decision', 'services', 'confidence', 'rationale', 'evidence', 'available_evidence', 'reviewer']
    for name in ['reviewer_A.csv', 'reviewer_B.csv']:
        with (folder/name).open('x', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader(); writer.writerows(rows)
    headers = ['class', 'decision', 'services', 'rationale', 'evidence', 'reviewer_A_decision',
               'reviewer_A_services', 'reviewer_B_decision', 'reviewer_B_services', 'adjudicator', 'date', 'disagreement_resolution']
    with (folder/'adjudication.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader(); writer.writerows({'class': name} for name in store.classes)
    (folder/'REVIEWER_GUIDE.md').write_text(GUIDE, encoding='utf-8')
    (folder/'evidence_index.json').write_text(json.dumps(index, indent=2)+'\n', encoding='utf-8')
    graph = json.loads(inside('results/dependency_baseline/petclinic_k5.json').read_text(encoding='utf-8'))
    (folder/'static_dependencies.json').write_text(json.dumps({'nodes': graph['nodes'],
        'direct_typed_edges': graph['direct_typed_edges'], 'limitations': graph['limitations']}, indent=2)+'\n', encoding='utf-8')
    for name in ['LICENSE.txt', 'PROVENANCE.md']:
        shutil.copyfile(inside('sample_petclinic/'+name), folder/name)
    manifest = {'eligible_source_fingerprint': store.snapshot['eligible_java_files_sha256'],
        'upstream_commit': None, 'dependency_sha256': store.graph_sha256, 'classes': store.classes,
        'human_answers_filled': False, 'files': {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file()}}
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('Prepared blank independent-review package', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    prepare(parser.parse_args().output_dir)
