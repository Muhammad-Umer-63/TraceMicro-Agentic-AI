"""Run one planning-cap variant in the existing final-day PetClinic session."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
import time

from petclinic_final_day_live import CUTOFF, RESULTS
from petclinic_full_scope_review import groups
from petclinic_global_plan import CAP2048_VERSION, PlanSessionBudget, run
from tracemicro.pilot import ROOT


CAP_MANIFEST = RESULTS / 'frozen_cap2048.json'


def verify_manifest(path, alternate=None):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    alternate = alternate or {}
    for name, expected in manifest['files'].items():
        source = alternate.get(name, ROOT / name)
        if sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Frozen artifact changed: {name}')
    return manifest


def remaining_seconds(limits, budget, now):
    started = datetime.fromisoformat(limits['started_utc'])
    cutoff = datetime.fromisoformat(limits['development_cutoff'])
    allocated = limits['allocated_wall_seconds']
    if cutoff != CUTOFF or not 0 < allocated <= 3600:
        raise ValueError('Unexpected session time limits')
    utc_deadline = min(started + timedelta(seconds=allocated), cutoff)
    wall_remaining = (utc_deadline - now).total_seconds()
    tick = budget.clock()
    monotonic_remaining = budget.deadline_monotonic - tick
    if not 0 <= tick - budget.last_finished <= allocated or abs(wall_remaining - monotonic_remaining) > 5:
        raise ValueError('Original UTC and monotonic session clocks do not agree')
    return min(wall_remaining, monotonic_remaining)


def main():
    if not os.environ.get('GROQ_API_KEY', '').strip():
        raise SystemExit('GROQ_API_KEY is absent from this process. No requests made.')
    session = RESULTS / 'live_v3'
    ledger_path = session / 'session_budget.json'
    if not ledger_path.is_file():
        raise SystemExit('Original live session ledger is required.')
    verify_manifest(CAP_MANIFEST)
    limits = json.loads((session / 'session_limits.json').read_text(encoding='utf-8'))
    # An exclusive claim preserves the first continuation attempt even if interrupted.
    claim = session / 'cap2048_attempt_1.json'
    if claim.exists() or (session / 'run_2_cap2048').exists():
        raise SystemExit('The cap2048 attempt already has a saved record.')
    budget = PlanSessionBudget(ledger_path)
    if budget.requests != 1 or budget.wait_total != 0 or budget.last_finished is None:
        raise SystemExit('Original request ledger has advanced. Inspect it before continuing.')
    if (limits['requests'], limits['interval_seconds'], limits['requested_wait_seconds']) != (
            budget.max_requests, budget.interval, budget.max_wait):
        raise SystemExit('Original limits and ledger disagree.')
    now = datetime.now(timezone.utc)
    remaining = remaining_seconds(limits, budget, now)
    if remaining < 10 * (60 + 15):
        raise SystemExit('Original session has insufficient time for an expected first-pass run.')
    with claim.open('x', encoding='utf-8') as stream:
        json.dump({'condition': CAP2048_VERSION, 'started_utc': now.isoformat(),
                   'original_ledger': json.loads(ledger_path.read_text(encoding='utf-8')),
                   'remaining_seconds_at_start': remaining}, stream, indent=2)
        stream.write('\n')
    folder = session / 'run_2_cap2048'
    summary = run(folder, budget, allow_live=True, condition=CAP2048_VERSION)
    rows = summary['accepted_assignments']
    keys = ('status', 'plan', 'planning_findings', 'combined_findings', 'global_transport_attempts',
            'session_transport_attempts', 'reported_tokens', 'records_missing_token_fields',
            'global_wait_seconds', 'total_elapsed_seconds')
    result = {key: summary[key] for key in keys}
    result.update(accepted_classes=len(rows), groups=groups(rows),
                  shared_classes=[row['class'] for row in rows if row['shared']])
    print(json.dumps(result, indent=2))
    print('Saved:', folder.relative_to(ROOT), flush=True)
    raise SystemExit(summary['status'] != 'basic_checks_passed')


if __name__ == '__main__':
    main()
