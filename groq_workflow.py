"""Explicitly opted-in Groq live smoke CLI. Never called automatically."""
import argparse
import json
from pathlib import Path

from tracemicro.evidence import EvidenceStore
from tracemicro.providers import GroqConfig, GroqProvider, ProviderError
from tracemicro.workflow import Budget, Workflow

ROOT = Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live',action='store_true')
    parser.add_argument('--list-models',action='store_true')
    parser.add_argument('--model',help='Exact account-accessible chat/JSON-mode model ID, no default')
    parser.add_argument('--output',default='results/groq_live/smoke.json')
    args=parser.parse_args()
    if not args.allow_live: parser.error('Explicit --allow-live required; no request made')
    if not args.list_models and not args.model: parser.error('Select an available model explicitly; no default')
    provider=GroqProvider(GroqConfig(model=args.model or 'model-list-only'),allow_live=True)
    try:
        if args.list_models:
            print(json.dumps({'available_model_ids':provider.list_models()},indent=2)); return
        saved=json.loads((ROOT/'results/dependency_baseline/petclinic_k5.json').read_text())
        store=EvidenceStore(ROOT,'sample_petclinic','results/dependency_baseline/petclinic_raw.json',
                            saved['snapshot']['eligible_java_files_sha256'],saved['raw_analyzer_sha256'])
        scope=['org.springframework.samples.petclinic.model.BaseEntity']
        doc=Workflow(store,provider,scope,['candidate_service'],Budget(2,1,0)).run(args.output)
        print(json.dumps({'run_kind':doc['run_kind'],'termination_reason':doc['state']['termination_reason'],
                          'requests_attempted':provider.request_count,'trace':args.output},indent=2))
        if doc['state']['termination_reason'] != 'basic_checks_passed':
            raise SystemExit(1)
    except ProviderError as error:
        detail = 'HTTP '+str(error.status)+'; response origin unverified' if error.source == 'http_response' else error.source
        parser.exit(1,'Groq request failed: '+error.code+' ['+detail+']\n')


if __name__ == '__main__': main()
