# Evidence for the TraceMicro development case study

TraceMicro explores evidence-linked service assignment on one fixed PetClinic source subset. MicroAgent is the base paper. TraceMicro uses the authors' static analyzer output. A matched evaluation of the full MicroAgent model pipeline remains open. [MicroAgent](https://doi.org/10.1145/3832783.3834441) · [Artifact provenance](../vendor/provenance.json)

## Inputs and measured conditions

The eligible Java content fingerprint is `c66415bfe029129bc8229a36216547dd41c3ba32d7aad5b8590dd00ac4622e29`. Five package-info files are excluded. The graph export SHA-256 is `c597fc90b251082482cdaf89f0d463251d0c8d9c65db20bbad4948d131cdd8b4`. The historical analyzer execution recorded exit code zero and JAR SHA-256 `b5508a974cb71cdded308fda96ee8a9cdefe9284dfb891f949131e46fe80fd67`. The raw execution log with local paths stays in the working archive. Six source excerpts are partial. Analyzer edges lack source-line references and complete resolution diagnostics. [Snapshot provenance](../sample_petclinic/PROVENANCE.md) · [Exact graph export](../results/dependency_baseline/petclinic_raw.json) · [Saved clustering](../results/dependency_baseline/petclinic_k5.json)

A crossing occurs when the endpoints share no service. For complete outputs the denominators are 59 typed directed records and 42 distinct directed pairs. Package grouping crosses 14/59 and 14/42. Dependency clustering and the three original model outputs cross zero on both denominators. A single group always has zero crossings.

| Original run | Requests | Reported tokens | Pacing / elapsed seconds |
|---|---:|---:|---:|
| [First complete run](../results/submit_only_live_20261122_1827/attempt_1/summary.json) | 9 | 47,837 | 479.799 / 491.156 |
| [Repetition 1](../results/reproducibility_live_20261122_1847/run_1/summary.json) | 9 | 48,077 | 479.859 / 492.797 |
| [Repetition 2](../results/reproducibility_live_20261122_1847/run_2/summary.json) | 9 | 48,564 | 539.109 / 550.485 |

All 27 requests in the series report usage. The original submit-only configuration precollects 50 evidence records and processes nine batches with Groq openai/gpt-oss-20b at temperature zero and 1,024 requested output tokens per call. Each pair of runs agrees on the full group-membership neighborhoods for all 25 classes. The validator checks shape, coverage, allowed labels, sharing and same-class citations. The three-class interactive pilot used seven model requests and six local inspections, reported 24,401 tokens, and assigned BaseEntity to both groups. [Pilot](../results/groq_live/langgraph_pilot_1.json) · [Frozen workflow hashes](../results/global_plan_development_20261123/freeze.json)

| Other recorded attempts | Accepted classes | Outcome |
|---|---:|---|
| [Early live_1](../results/petclinic_batch_groq/live_1/summary.json) | 0/25 | Invalid labels |
| [Early live_2](../results/petclinic_batch_groq/live_2/summary.json) and [live_3](../results/petclinic_batch_groq/live_3/summary.json) | 3/25 each | HTTP 400 in batch 2 |
| [Network attempt](../results/full_scope_session_20261122/attempt_1/summary.json) | 0/25 | No HTTP response |
| [Global plan v1](../results/global_plan_live_v1_20261123/run_1/summary.json) | 0/25 | Planning HTTP 413 |
| [Compact v2](../results/course_live_20261123_2201/compact_run_1/summary.json) | 0/25 | Planning HTTP 400 with an empty failure-generation field |
| [Reduced-context probe](../results/course_live_20261123_2201/planning_probe_1/probe.json) | Plan only | One input class, one request, 1,358 reported tokens |
| [Compact v3 fixture](../results/restart_readiness_20261124_0715/simulated_single/summary.json) | 25 artificial assignments | Injected transport simulation |

Each attempt retains its original run label. Unknown usage remains unknown. The probe is a release derivative with its local source path replaced by a repository-relative reference. Numeric values and provider diagnostics are preserved. The three original completed runs are comparable repetitions. Earlier conditions use different request contracts.

## Approved research gaps

| Gap | Implementation and evidence |
|---|---|
| G1. Reliability when architectural evidence is incomplete | Static warnings and synthetic runtime-mask and recovery fixtures. Real scenario evidence and measured recovery effects remain open. |
| G2. Independent verification of decomposition recommendations | Local structural validation ran live. Advisory criticism has synthetic evidence. Independent adjudicated references and measured error reductions remain open. |
| G3. Quality–cost trade-offs in agent coordination | Live generator accounting and offline fixed/selective routing replay exist. Matched live quality–cost measurements remain open. |

There is no independent architectural-quality result on PetClinic. JPetStore and AcmeAir are reserved for held-out work. Reference labels and reviewer materials are outside this checkpoint.
