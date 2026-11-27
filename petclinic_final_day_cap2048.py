"""Run the frozen planning variant once under a fresh 15-request budget."""
from datetime import datetime, timezone
import json
import os
import time

from petclinic_batch_groq import GlobalBudget
from petclinic_final_day_continue import CAP_MANIFEST, verify_manifest
from petclinic_final_day_live import CUTOFF, RESULTS
from petclinic_full_scope_review import groups
from petclinic_global_plan import CAP2048_VERSION, run
from tracemicro.pilot import ROOT


SESSION = RESULTS / 'live_cap2048_25m'
MAX_REQUESTS = 15
WALL_SECONDS = 25 * 60
INTERVAL_SECONDS = 60
MAX_WAIT_SECONDS = (MAX_REQUESTS - 1) * INTERVAL_SECONDS


def main():
    if not os.environ.get('GROQ_API_KEY', '').strip():
        raise SystemExit('GROQ_API_KEY is absent from this process. No requests made.')
    verify_manifest(CAP_MANIFEST)
    started = datetime.now(timezone.utc)
    seconds = min(WALL_SECONDS, (CUTOFF - started).total_seconds())
    if seconds < 9 * INTERVAL_SECONDS + 10 * 15:
        raise SystemExit('Insufficient time before the development cutoff for a first-pass run.')
    deadline = time.monotonic() + seconds
    SESSION.mkdir(exist_ok=False)
    budget = GlobalBudget(MAX_REQUESTS, INTERVAL_SECONDS, MAX_WAIT_SECONDS,
                          deadline_monotonic=deadline,
                          checkpoint_path=SESSION / 'session_budget.json')
    limits = {'condition': CAP2048_VERSION, 'started_utc': started.isoformat(),
              'development_cutoff': CUTOFF.isoformat(), 'allocated_wall_seconds': seconds,
              'requests': MAX_REQUESTS, 'interval_seconds': INTERVAL_SECONDS,
              'requested_wait_seconds': MAX_WAIT_SECONDS}
    (SESSION / 'session_limits.json').write_text(json.dumps(limits, indent=2) + '\n', encoding='utf-8')
    budget.save()
    folder = SESSION / 'run_1_cap2048'
    result = run(folder, budget, allow_live=True, condition=CAP2048_VERSION)
    rows = result['accepted_assignments']
    keys = ('status', 'plan', 'planning_findings', 'combined_findings',
            'global_transport_attempts', 'reported_tokens', 'records_missing_token_fields',
            'global_wait_seconds', 'total_elapsed_seconds')
    report = {key: result[key] for key in keys}
    report.update(accepted_classes=len(rows), groups=groups(rows),
                  shared_classes=[row['class'] for row in rows if row['shared']])
    print(json.dumps(report, indent=2))
    print('Saved:', folder.relative_to(ROOT), flush=True)
    raise SystemExit(result['status'] != 'basic_checks_passed')


if __name__ == '__main__':
    main()
