# TraceMicro

TraceMicro recommends candidate service memberships for Java classes and records the source and dependency evidence behind each assignment. This development checkpoint uses a fixed PetClinic source subset and a saved static dependency graph from the MicroAgent analyzer.

## What the experiment measured

| Completed condition | Eligible classes assigned | Nonempty group sizes |
|---|---:|---|
| Package baseline | 25/25 | 11, 5, 4, 3, 2 |
| Dependency baseline, fixed k=5 | 25/25 | 21, 1, 1, 1, 1 |
| Original Groq workflow, three runs | 25/25 each | One group of 25 in each run |

All three original runs passed local coverage and citation checks. Each assigned every class to candidate_1. The smaller live pilot represented shared membership. Two full planning attempts failed before assignment. A reduced-context probe returned a plan, and a full bounded planner completed under simulated transport. Architectural quality and improvements on the approved gaps remain unmeasured. [Methods, evidence paths and limitations](docs/PAPER_EVIDENCE.md)

The checkpoint includes the editable paper in IEEE and ACM formats. The build instructions record the current toolchain blocker and draft status. [Paper sources and build instructions](Paper/reviewed_v2/README.md)

## Offline setup and demo

The recorded staging check used Windows, Python 3.10.11 and LangGraph 0.6.11. To prepare a new environment later, run from the repository root in PowerShell:

    py -3.10 -m venv .venv-langgraph
    .\.venv-langgraph\Scripts\python.exe -m pip install -r requirements.txt

The demo uses the saved graph. It needs neither Java nor a provider key. From the root, use a fresh output directory:

    $py = '.\.venv-langgraph\Scripts\python.exe'
    $out = 'verification_outputs/demo_' + [guid]::NewGuid().ToString('N')
    & $py -I -B -X utf8 tools/verify_release_offline.py --output-dir $out

This command runs the following offline entry points and records their outputs under $out:

| Entry point | Output and expected result |
|---|---|
| baseline.py | package.json matches the archived class memberships and assigns 25 classes |
| dependency_baseline.py | dependency.json has 25 nodes, 59 typed directed records, 42 distinct directed pairs and groups 21/1/1/1/1 |
| petclinic_comparison.py | three_classes.json compares package / dependency / saved live group counts of 3/1/2 |
| petclinic_full_scope_review.py | full_review/review.json and assignments.csv show 25/25 membership agreement for each pair of original live runs |
| tools/check_langgraph_offline.py | offline_checks/tests.log and summary.json. Staging recorded 142 passing tests, including graph integration and transport fixtures. Node-harness replays are reported separately. |

The runner blocks Python socket operations and external process launches during these checks. Replaying a recorded trace reads an old result. Some test fixtures use mock transport and synthetic credentials. [Trace responsibilities and expected resource totals](docs/PAPER_EVIDENCE.md)

## Optional live workflow

Use an explicitly authorized session and configure GROQ_API_KEY through the process environment. The supplied .env.example is a placeholder reference. To run the original bounded full-scope condition once, use fresh output paths:

    $live = 'results/local_live_' + [guid]::NewGuid().ToString('N')
    & $py -B -X utf8 petclinic_live_session.py --allow-live --model openai/gpt-oss-20b --session-ledger "$live/session_budget.json" --output-dir "$live/run_1" --wall-seconds 1800 --max-requests 18 --pace-seconds 60 --max-wait-seconds 1020

This uses a hosted provider and may incur costs. Outputs from a fresh live run can differ. Keep its artifacts separate from the recorded series and start with a fresh ledger after a reboot.

## Data, licenses and attribution

The PetClinic Java subset retains the upstream Apache license and source notices. Its content hash identifies these files. The upstream commit and acquisition date remain unknown. The analyzer subset retains its MIT license and attribution. TraceMicro’s own license is a separate owner decision. [PetClinic provenance](sample_petclinic/PROVENANCE.md) · [Analyzer attribution](working/microagent-analyzer-original/ATTRIBUTION_TRACEMICRO.md) · [MicroAgent artifact provenance](vendor/provenance.json)
