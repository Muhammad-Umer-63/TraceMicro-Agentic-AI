"""One live attempt with a persistent shared cap/deadline across fresh attempts."""
import argparse
import json
import time
from pathlib import Path

from petclinic_batch_groq import GlobalBudget, run
from tracemicro.pilot import ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live',action='store_true')
    parser.add_argument('--model',required=True)
    parser.add_argument('--session-ledger',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--wall-seconds',type=int,default=1800)
    parser.add_argument('--max-requests',type=int,default=18)
    parser.add_argument('--pace-seconds',type=float,default=60)
    parser.add_argument('--max-wait-seconds',type=float,default=1020)
    args=parser.parse_args()
    if not args.allow_live: parser.error('Explicit --allow-live required')
    if not 1<=args.wall_seconds<=2400: parser.error('Wall limit must be 1..2400seconds')
    ledger=(ROOT/Path(args.session_ledger)).resolve(); ledger.relative_to(ROOT)
    budget=GlobalBudget(args.max_requests,args.pace_seconds,args.max_wait_seconds,
        deadline_monotonic=time.monotonic()+args.wall_seconds,checkpoint_path=ledger)
    budget.save()
    result=run(args.output_dir,model=args.model,allow_live=True,max_requests=args.max_requests,
        interval=args.pace_seconds,max_wait=args.max_wait_seconds,global_budget=budget)
    print(json.dumps({k:result[k] for k in ['status','global_transport_attempts',
        'session_transport_attempts','reported_tokens','global_wait_seconds','total_elapsed_seconds']},indent=2))
    if result['status']!='basic_checks_passed': raise SystemExit(1)


if __name__=='__main__': main()
