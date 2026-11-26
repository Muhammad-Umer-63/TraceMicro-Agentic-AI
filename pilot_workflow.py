"""Configurable PetClinic development pilot. Offline scripted mode is the default."""
import argparse
import json

from tracemicro.pilot import load_config,make_workflow,scripted_actions
from tracemicro.providers import GroqConfig,GroqProvider,ScriptedProvider


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/petclinic_pilot.json')
    parser.add_argument('--allow-live',action='store_true')
    parser.add_argument('--model',help='Exact model ID explicitly selected for a future live run')
    parser.add_argument('--structured-output',action='store_true',help='Opt-in strict workflow schema for openai/gpt-oss-20b')
    parser.add_argument('--pace-seconds',type=float,default=0,help='Optional wait after previous response, 0..60 seconds')
    parser.add_argument('--max-pacing-wait-seconds',type=float,default=0,help='Total requested wait cap, 0..420 seconds; no retries')
    parser.add_argument('--output',default='results/petclinic_pilot/offline_scripted.json')
    args=parser.parse_args()
    config=load_config(args.config)
    if args.allow_live:
        if not args.model: parser.error('Live pilot requires explicit --model; no request made')
        if args.output=='results/petclinic_pilot/offline_scripted.json':
            parser.error('Live mode requires an explicit new output path')
        limits=config['limits']
        provider=GroqProvider(GroqConfig(model=args.model,max_requests=limits['model_requests'],
                              max_output_tokens=limits['max_output_tokens'],timeout_seconds=limits['timeout_seconds'],
                              max_input_bytes=limits['max_input_bytes'],min_interval_seconds=args.pace_seconds,
                              max_pacing_wait_seconds=args.max_pacing_wait_seconds,structured_outputs=args.structured_output),allow_live=True)
    else:
        if args.structured_output: parser.error('Structured-output transport mode requires --allow-live')
        if args.pace_seconds or args.max_pacing_wait_seconds: parser.error('Pacing is for explicitly enabled live mode only')
        if args.model: parser.error('--model is only used with --allow-live')
        provider=ScriptedProvider(scripted_actions(config))
    doc=make_workflow(config,provider).run(args.output)
    print(json.dumps({'run_kind':doc['run_kind'],'scope':doc['state']['scope'],
                      'termination_reason':doc['state']['termination_reason'],
                      'trace':args.output},indent=2))
    if doc['state']['termination_reason']!='basic_checks_passed': raise SystemExit(1)


if __name__=='__main__': main()
