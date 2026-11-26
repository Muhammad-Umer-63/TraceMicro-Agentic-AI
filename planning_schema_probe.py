"""One diagnostic request with the failed planner's schema/settings and reduced evidence."""
import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import time

from petclinic_batch_groq import token_totals
from petclinic_global_plan import PlanProvider, PlanSessionBudget, save, validate_plan
from tracemicro.pilot import inside
from tracemicro.providers import GroqConfig, ProviderError


def reduced_context(context):
    result = copy.deepcopy(context)
    selected = context['state']['scope'][0]
    result['state']['scope'] = [selected]
    result['state']['evidence'] = {eid: row for eid, row in context['state']['evidence'].items() if row['class'] == selected}
    named = {selected} | {target for row in result['state']['evidence'].values() for target, kind in row.get('outgoing', [])}
    result['class_names'] = {key: value for key, value in context['class_names'].items() if key in named}
    result['source_excerpt_coverage'] = [row for row in context['source_excerpt_coverage'] if row['class'] == selected]
    return result


def run(source, output, budget, *, allow_live=False, transport=None):
    if not allow_live and transport is None:
        raise ValueError('Explicit diagnostic live authorization required')
    source, folder = inside(source), inside(output)
    failed = json.loads((source/'planning.json').read_text(encoding='utf-8'))
    summary = json.loads((source/'summary.json').read_text(encoding='utf-8'))
    settings = summary['planning_provider_config']
    config = GroqConfig(**settings)
    provider = PlanProvider(config, budget, allow_live=allow_live, transport=transport,
                            clock=budget.clock, sleeper=budget.sleep)
    prior = failed['model_usage'][0]
    wire_schema = provider.prepare_request([])['body']['response_format']
    if wire_schema != prior['response_format'] or provider.structured_instructions() != (prior['wire_instruction'], prior['system_instruction']):
        raise ValueError('Planner changed since failure; diagnostic comparison needs review')
    context = reduced_context(failed['context'])
    folder.mkdir(parents=True, exist_ok=False)
    result = {'run_kind': 'diagnostic_groq_live' if transport is None else 'diagnostic_simulated_http',
        'diagnostic_only': True, 'full_scope_decomposition': False,
        'source': str(source), 'source_planning_sha256': hashlib.sha256((source/'planning.json').read_bytes()).hexdigest(),
        'provider_config': asdict(config), 'context': context,
        'changed_condition': 'Only context scope/evidence/class-name mapping/coverage reduced to first class; same schema, instructions and generation settings.',
        'status': 'prepared'}
    save(folder/'probe.json', result)
    before, before_wait, started = budget.requests, budget.wait_total, time.monotonic()
    try:
        action = provider.decide(context)
        output_value = action.get('output') if action.get('type') == 'submit' else None
        findings = validate_plan(output_value, context['state']['evidence'])
        result.update(status='probe_passed' if not findings else 'probe_invalid', output=output_value, findings=findings)
    except Exception as error:
        result.update(status='probe_failed', error_type=type(error).__name__)
        if isinstance(error, ProviderError): result.update(error_code=error.code, http_status=error.status)
    result.update(global_transport_attempts=budget.requests-before, session_transport_attempts=budget.requests,
        wait_seconds=budget.wait_total-before_wait, elapsed_seconds=time.monotonic()-started,
        **token_totals(provider.records), model_usage=provider.records,
        live_model_run=transport is None and budget.requests > before)
    save(folder/'probe.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--session-ledger', required=True)
    parser.add_argument('--allow-live', action='store_true')
    args = parser.parse_args()
    if not args.allow_live: parser.error('--allow-live required')
    budget = PlanSessionBudget(inside(args.session_ledger))
    result = run(args.source, args.output_dir, budget, allow_live=True)
    print(json.dumps({k: result[k] for k in ['status', 'global_transport_attempts', 'reported_tokens']}))
    raise SystemExit(result['status'] != 'probe_passed')
