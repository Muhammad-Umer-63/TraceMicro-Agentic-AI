"""Run the frozen compact v3 condition in one bounded provider session."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
import time

from petclinic_full_scope_review import groups
from petclinic_global_plan import PlanSessionBudget, run
from tracemicro.pilot import ROOT


RESULTS = ROOT / 'results/final_day_20261127'
CUTOFF = datetime(2026, 11, 27, 17, 30, tzinfo=timezone(timedelta(hours=5)))


def verify_frozen_inputs():
    manifest = json.loads((RESULTS / 'frozen_inputs.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        if sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Frozen input changed: {name}')


def main():
    if not os.environ.get('GROQ_API_KEY', '').strip():
        raise SystemExit('GROQ_API_KEY is absent from this process. No requests made.')
    if not os.isatty(0):
        raise SystemExit('Run interactively in ordinary PowerShell for the review pause.')
    verify_frozen_inputs()
    seconds = min(3600, (CUTOFF - datetime.now(timezone.utc)).total_seconds())
    if seconds < 9 * 60 + 10 * 15:
        raise SystemExit('Insufficient time before the development cutoff. No requests made.')

    session = RESULTS / 'live_v3'
    session.mkdir(exist_ok=False)
    deadline = time.monotonic() + seconds
    budget = PlanSessionBudget(session / 'session_budget.json')
    budget.deadline_monotonic = deadline
    (session / 'session_limits.json').write_text(json.dumps({
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'development_cutoff': CUTOFF.isoformat(), 'allocated_wall_seconds': seconds,
        'requests': 40, 'interval_seconds': 60, 'requested_wait_seconds': 2340,
    }, indent=2) + '\n', encoding='utf-8')
    budget.save()

    for index in range(1, 4):
        if index > 1 and (40 - budget.requests < 10 or deadline - time.monotonic() < 10 * 60 + 10 * 15):
            print('Remaining shared budget cannot accommodate a first-pass repeat.')
            break
        folder = session / f'run_{index}'
        result = run(folder, budget, allow_live=True)
        assignments = result['accepted_assignments']
        keys = ('status', 'plan', 'planning_findings', 'combined_findings',
                'global_transport_attempts', 'reported_tokens', 'records_missing_token_fields',
                'global_wait_seconds', 'total_elapsed_seconds')
        review = {key: result[key] for key in keys}
        review.update(groups=groups(assignments), covered=len(assignments),
                      shared=[row['class'] for row in assignments if row['shared']],
                      total_session_requests=budget.requests)
        print(json.dumps(review, indent=2))
        print('Saved:', folder.relative_to(ROOT), flush=True)
        if result['status'] == 'failed_plan' or (index == 1 and result['status'] != 'basic_checks_passed'):
            print('Series stopped. Inspect the saved failure and preserve the ledger.')
            break
        if index == 1:
            try:
                answer = input('Review the saved plan and assignments. Type REPEAT to run up to two unchanged repeats: ')
            except EOFError:
                break
            if answer.strip() != 'REPEAT':
                break
            verify_frozen_inputs()


if __name__ == '__main__':
    main()
