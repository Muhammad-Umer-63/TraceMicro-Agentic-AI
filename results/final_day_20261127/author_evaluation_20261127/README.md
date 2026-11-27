# PetClinic author development evaluation

**Author-reviewed development reference; reviewer has seen model outputs.** The author explicitly approved the worksheet after ChatGPT assistance. The saved [approval receipt](reference_receipt.json) records the provenance and supersedes the pending-approval wording in the byte-identical [reference CSV](author_reference_20261127.csv). Its SHA-256 is `6c7b6e67e3267d356beb04ea6bc2c628bf1a98637c8f06bd8349c0931fe67906`.

Validation checked the exact 25 eligible class IDs, memberships, confidence fields, rationales, evidence filename references and linked source bytes. The reference has 16 domain, 3 shared and 6 infrastructure decisions, with no uncertain or excluded rows. The labels express the author's approved judgments.

| Method | Coverage | Domain pair precision | Domain pair recall | Domain pair F1 | Shared-class F1 | Shared-anchor F1 |
|---|---:|---:|---:|---:|---:|---:|
| Package baseline | 25/25 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| Dependency baseline | 25/25 | 0.542 | 1.000 | 0.703 | 0.000 | 0.000 |
| Original run 1 | 25/25 | 0.542 | 1.000 | 0.703 | 0.000 | 0.000 |
| Original run 2 | 25/25 | 0.542 | 1.000 | 0.703 | 0.000 | 0.000 |
| Original run 3 | 25/25 | 0.542 | 1.000 | 0.703 | 0.000 | 0.000 |

All five identify the 65 annotated positive domain pairs. The package baseline adds no false positives among reference domain classes. The other four each add 55. Every method misses all 3 shared classes and all 48 shared-to-domain anchor associations, with undefined precision for both shared metrics because no positive instances were predicted. Domain-pair scoring excludes shared and infrastructure classes. The group partitions in the author reference align with owner and vet packages on the scored domain classes. These results describe agreement with one AI-assisted, model-exposed author on the PetClinic development snapshot. Independent accuracy, held-out performance, matched MicroAgent results and G1–G3 improvements remain unmeasured.

The separate [reliability export](evaluation/reliability.csv) contains all 18 registered live records, both final-day failures and the reduced planning probe. Eight of the eleven full-scope attempts failed across different configurations. Six of the nine limited-scope records failed. These are historical counts and conditions vary. Only the two deterministic baselines and the three completed original runs were agreement-scored.

## Reproduce offline in PowerShell

Run from the workspace root in the existing project virtual environment, or substitute the Python executable from a project-local environment created from the pinned requirements. Choose a fresh output directory.

```powershell
.\.venv-langgraph\Scripts\python.exe -B -X utf8 petclinic_author_evaluation.py --output-dir results/final_day_20261127/reproduced_author_evaluation
```

Expect five scored outputs against 25 decisions and 21 live reliability or diagnostic records. The command verifies the frozen reference and archived run hashes. It writes `agreement.csv`, `agreement.json`, `reliability.csv` and the five structural comparison exports. The evaluator blocks sockets. Blank precision and missing provider usage denote unavailable values.
