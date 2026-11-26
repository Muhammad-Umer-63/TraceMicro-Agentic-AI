"""Offline scripted foundation smoke test. No model, networking or key access."""
import argparse
import json
from pathlib import Path

from tracemicro.evidence import EvidenceStore
from tracemicro.providers import ScriptedProvider
from tracemicro.workflow import Budget, Workflow

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='results/workflow_foundation/scripted_smoke.json')
    args = parser.parse_args()
    saved = json.loads((ROOT/'results/dependency_baseline/petclinic_k5.json').read_text())
    store = EvidenceStore(ROOT,'sample_petclinic','results/dependency_baseline/petclinic_raw.json',
                          saved['snapshot']['eligible_java_files_sha256'],saved['raw_analyzer_sha256'])
    prefix = 'org.springframework.samples.petclinic.'
    owner, pet, base = prefix+'owner.Owner',prefix+'owner.Pet',prefix+'model.BaseEntity'
    # Hand-authored protocol fixture, not generated or validated domain recommendations.
    initial = [{'class':owner,'services':['owners'],'shared':False,'evidence':['E1']},
               {'class':base,'services':['owners','vets'],'shared':True,'evidence':['E3']}]
    final = initial+[{'class':pet,'services':['owners'],'shared':False,'evidence':['E2']}]
    actions = [{'type':'inspect_source','class':n} for n in [owner,pet,base]]
    actions += [{'type':'inspect_dependencies','class':owner},
                {'type':'submit','output':{'assignments':initial}},
                {'type':'submit','output':{'assignments':final}}]
    doc = Workflow(store,ScriptedProvider(actions),[owner,pet,base],['owners','vets'],Budget(6,4,1)).run(args.output)
    print(json.dumps({'run_kind':doc['run_kind'],'live_model_run':False,
                      'scope_classes':len(doc['state']['scope']),'input_classes':len(store.classes),
                      'termination_reason':doc['state']['termination_reason'],
                      'trace':args.output},indent=2))


if __name__ == '__main__': main()
