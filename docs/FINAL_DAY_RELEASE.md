# TraceMicro submission checkpoint

The final-day comparison and exact offline command are in [the results README](../results/final_day_20261127/README.md). The development deadline is 17:30 PKT on 27 November 2026. The submission deadline is 19:00 PKT.

The [final author evaluation](../results/final_day_20261127/author_evaluation_20261127/README.md) provides the frozen reference, approval receipt, agreement and reliability tables, and exact offline command. The paper reports AI assistance and prior model exposure.

## Recorded live cap2048 attempt

The 1,024-token plan ended with `finish_reason=length` before an action was parsed. The continuation changes only the planning completion allowance to 2,048. The observed 2,440 prompt tokens plus that allowance total 4,488, below the saved 8,000 token-per-minute limit. 2,048 is within the client's existing guard and Groq's model ceiling. The model, prompt, schema, input, assignment settings and 60-second pacing are held fixed. [Groq model limits](https://console.groq.com/docs/model/openai/gpt-oss-20b) · [Groq rate limits](https://console.groq.com/docs/rate-limits)

The recorded launcher was run from the workspace root in ordinary PowerShell:

```powershell
.\.venv-langgraph\Scripts\python.exe -B -X utf8 petclinic_final_day_cap2048.py
```

The original continuation stopped at its time preflight. The separately authorized session used the frozen variant with at most 15 requests and 25 minutes. It accepted a plan and terminated in its first batch with HTTP 400 and `json_validate_failed`. See [the diagnosis and staged resource breakdown](../results/final_day_20261127/comparison_cap2048/diagnosis.md). Preserve both ledgers and use the offline comparison for submission preparation.

## Minimal synchronization for the existing release

The [GitHub synchronization manifest](FINAL_EVALUATION_GITHUB_SYNC.csv) lists exact relative paths and hashes. It records changes against the 26 November staged candidate. The separate clone was outside scope. Verify that the clone has the matching staged dependencies and preserves bytes on checkout. Include the manifest itself and keep all files at the listed relative paths. Link this note from the clone README if incorporating this checkpoint into the release. Submit the Overleaf ZIP separately.

The group owner reviews the changes, runs the offline comparison from the clone, commits and pushes, and creates `phase2-final`. Retain the existing safe placeholder from the staged release and the repository's checkout attributes.

## Submission preparation

1. Open [the final IEEE Overleaf ZIP](../Paper/TraceMicro_20261127_final_IEEE_Overleaf.zip) as a new project and compile with pdfLaTeX and BibTeX. Inspect the 8–10-page requirement, citations, tables, title metadata and instructor note. The source check preserved the v4 title layout. The course PDF also specifies project code and roll numbers on the title page, so confirm any instructor exception or add those identifiers during your review.
2. Have the group verify and finalize its own manuscript, preserving the limitations and distinguishing measured results from unresolved course requirements. Generate both actual Turnitin reports from that same final PDF.
3. By 19:00 PKT, the group head submits the paper PDF, both Turnitin PDFs, the paper source ZIP, and the repository and `phase2-final` links in Google Classroom. Use the course naming convention and verify supervisor access.
