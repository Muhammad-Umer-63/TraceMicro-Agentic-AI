# PetClinic final-day result

The offline comparison recomputed both deterministic baselines from the fixed Java subset and analyzer graph. It revalidated the saved assignments, citations and accepted batches for the three historical model runs. Copies of those primary outputs and planning diagnostics are under `saved/`, with original paths and hashes in `saved/manifest.json`. The frozen contract and configuration hashes are in `CONTRACT.md` and `frozen_inputs.json`.

| Condition | Coverage | Group sizes | Shared classes | Crossing typed records | Crossing directed pairs |
|---|---:|---|---:|---:|---:|
| Package baseline | 25/25 | 11/5/4/3/2 | 0 | 14/59 | 14/42 |
| Dependency baseline | 25/25 | 21/1/1/1/1 | 0 | 0/59 | 0/42 |
| Original live method, each of three runs | 25/25 | 25 | 0 | 0/59 | 0/42 |

All three originals put every eligible class in `candidate_1`. Their class membership neighborhoods agree for all 25 classes in every pair of repeats. They total 27 completion attempts and 144,478 provider-reported tokens with complete usage records. Mean tokens per run were 48,159.3 (sample SD 370.4). Mean elapsed time was 511.5 seconds (sample SD 33.8), including pacing. A single group has zero crossing edges by definition.

Full-scope planning v1 failed with HTTP 413 and compact v2 failed with HTTP 400. Both stopped before any assignment, with one charged attempt and unknown token usage each. The compact v2 provider diagnostic records an empty rejected generation. The reduced one-class probe passed its plan checks in one call using 1,358 reported tokens and had no assignment stage. The compact v3 simulation used artificial assignments. Its fixture tokens and fixture pacing are separate from provider measurements.

**Live compact v3:** The 1,024-token planning request ended with `finish_reason=length`. Its 3,464 reported tokens comprised 2,440 prompt and 1,024 completion tokens. The client caught the length stop before action parsing or local plan validation. The run failed with 0/25 accepted, one request, zero pacing and 2.016 seconds elapsed. The [v3 failure comparison](comparison_v3_failure/comparison.csv) includes this result.

**Live cap2048:** The separately authorized session in `live_cap2048_25m/` recorded one accepted five-responsibility plan, then batch 1 failed with HTTP 400 and `json_validate_failed`. The run accepted 0/25 classes and took 63.547 seconds including 59.438 seconds of pacing. It used two requests. The plan reported 3,505 tokens and the failed assignment request reported no usage. The rejected generation was empty and the provider supplied no batch finish reason. The [updated comparison](comparison_cap2048/comparison.csv), [resources](comparison_cap2048/resources.csv) and [citation diagnosis](comparison_cap2048/diagnosis.md) preserve the observed stage outcomes. The earlier same-session continuation stopped in its preflight and issued no request.

**Author-reference agreement:** The approved AI-assisted worksheet is frozen and scored in the [author evaluation](author_evaluation_20261127/README.md), with prior model exposure disclosed. Independent architectural accuracy, a matched MicroAgent run, held-out evaluation and improvements on G1–G3 remain unmeasured. No billing data were supplied.

## Reproduce the saved comparison offline

Run from the workspace root with the project Python 3.10/LangGraph environment. Use a new output path. This command reads saved artifacts and makes no provider requests.

```powershell
.\.venv-langgraph\Scripts\python.exe -B -X utf8 petclinic_final_day_review.py --output-dir results/final_day_20261127/reproduced
```

Expected output includes:

```text
25 classes, 59 typed records, 42 directed pairs
5 complete conditions/runs, 4 saved full-scope failures, 2 terminal final-day attempts, 0 pending/interrupted
```

The five outputs are `comparison.json`, `comparison.csv`, `memberships.csv`, `resources.csv` and `group_sizes.svg`. The JSON includes pairwise neighborhood agreement, validation and planning findings, and resource totals. Blank token fields in the CSV mean unknown or not applicable. Per-field missing usage counts identify gaps in provider accounting. For a failed 0/25 run, zero covered crossing endpoints yields an undefined ratio.

These counts describe the final-day checkpoint with both live attempts. The comparison retains terminal failures and reports pending or interrupted directories and ledger charges per session. Use `--historical-only` for the two deterministic baselines, original runs and pre-final-day planning evidence.

## Author review

**Author-reviewed development reference; reviewer has seen model outputs.**

The author's approved decisions and disclosure are documented in the [approval receipt](author_evaluation_20261127/reference_receipt.json). The blank worksheet and the original draft remain in the development workspace.
