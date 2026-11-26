"""PetClinic LangGraph pilot; scripted by default, live requires explicit opt-in."""
import argparse
import json

from tracemicro.langgraph_workflow import LangGraphWorkflow
from tracemicro.pilot import load_config, make_workflow, scripted_actions
from tracemicro.providers import GroqConfig, GroqProvider, ScriptedProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/petclinic_pilot.json')
    parser.add_argument('--output', required=True, help='New trace path; never overwritten')
    parser.add_argument('--allow-live', action='store_true')
    parser.add_argument('--model', help='Exact model ID for an explicitly authorized live run')
    parser.add_argument('--structured-output', action='store_true')
    parser.add_argument('--pace-seconds', type=float, default=0)
    parser.add_argument('--max-pacing-wait-seconds', type=float, default=0)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.allow_live:
        if not args.model:
            parser.error('Live graph pilot requires explicit --model; no request made')
        limits = config['limits']
        provider = GroqProvider(GroqConfig(model=args.model,
            max_requests=limits['model_requests'], max_output_tokens=limits['max_output_tokens'],
            timeout_seconds=limits['timeout_seconds'], max_input_bytes=limits['max_input_bytes'],
            structured_outputs=args.structured_output, min_interval_seconds=args.pace_seconds,
            max_pacing_wait_seconds=args.max_pacing_wait_seconds), allow_live=True)
    else:
        if args.model or args.structured_output or args.pace_seconds or args.max_pacing_wait_seconds:
            parser.error('Model/structured-output/pacing options require --allow-live')
        provider = ScriptedProvider(scripted_actions(config))
    core = make_workflow(config, provider)
    try:
        document = LangGraphWorkflow(core, allow_live=args.allow_live).run(args.output)
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith('langgraph'):
            parser.exit(2, 'LangGraph is not installed. Use the project-local installation commands in docs/LANGGRAPH_DEVELOPMENT.md. No model call was made.\n')
        raise
    print(json.dumps({'run_kind':document['run_kind'],
                      'execution_engine':document['execution_engine'],
                      'termination_reason':document['state']['termination_reason'],
                      'trace':args.output}, indent=2))
    if document['state']['termination_reason'] != 'basic_checks_passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
