# TraceMicro paper sources

This is the editable draft. Both formats use the same canonical manuscript, bibliography, generated body and figures. Author names, affiliations and contact details are pending. The ACM entry point also has city and country placeholders.

- [Canonical manuscript](corrected_manuscript.md) and [bibliography](references.bib)
- [IEEE conference entry point](ieee/main.tex) and [ACM sigconf entry point](acm/main.tex)
- [Shared LaTeX inputs](shared/) and [vector figures and generator](figures/)
- [Experiment evidence](../../docs/PAPER_EVIDENCE.md)

## Compile and inspect

Run from `Paper/reviewed_v2` with a working TeX distribution. Install the official IEEEtran and acmart class packages, TikZ/PGF, BibTeX, and the fonts and dependencies requested by the classes. Build IEEE first, then ACM.

```powershell
latexmk -pdf -halt-on-error -interaction=nonstopmode -outdir=ieee/build -jobname=TraceMicro-IEEE-DRAFT ieee/main.tex
latexmk -pdf -halt-on-error -interaction=nonstopmode -outdir=acm/build -jobname=TraceMicro-ACM-DRAFT acm/main.tex
```

Expected build outputs are `ieee/build/TraceMicro-IEEE-DRAFT.pdf` and `acm/build/TraceMicro-ACM-DRAFT.pdf`. Read the build logs and render each page. Check unresolved references, clipped or overfull lines and tables, figure legibility, placeholder text and the 8–10-page requirement. Copy successful, inspected PDFs to the corresponding format folder outside `build/` if they are intended for the checkpoint. Retain a visible draft label on public unfinished copies and keep final release hashes current.

The checked workspace had no operational TeX engine or package lookup tool. A portable Tectonic download failed on DNS. Both formats remain uncompiled and page counts are unknown. No bibliography output file was generated. Keep a compiled .bbl separately if a submission system needs it.

## Regenerate editable inputs

From this directory run:

```powershell
python -B -X utf8 build_sources.py
python -B -X utf8 figures/generate_figures.py
```

The second command reads the saved baseline and original assignments from the repository. The included TikZ assets are sufficient to compile the paper. Keep the reference order consistent between the Markdown list and BibTeX. The current ten cited entries leave 15–20 additions for the stated 25–30 target if both documentation entries count, or 17–22 if they do not.
