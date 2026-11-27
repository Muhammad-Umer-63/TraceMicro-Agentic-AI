# TraceMicro v4 title page

The v4 package updates the title page from `Paper/reviewed_v3`. The manuscript body, abstract, bibliography and figures are carried forward. Edit author and instructor text in `corrected_manuscript.md`, then run `python -B -X utf8 build_sources.py` from this directory to regenerate shared LaTeX.

IEEE uses three conference author blocks and puts the centered instructor note in `\IEEEaftertitletext`, the full-width space above the abstract. ACM uses three author, affiliation and email records. A hook appends the note to acmart's title box after author layout and before the class prints the abstract. [IEEEtran class guide](https://tug.ctan.org/macros/latex2e/contrib/IEEEtran/IEEEtran_HOWTO.pdf) · [acmart title-box implementation](https://raw.githubusercontent.com/borisveytsman/acmart/primary/acmart.dtx)

## Compile

The [final 27 November IEEE source ZIP](../TraceMicro_20261127_final_IEEE_Overleaf.zip) includes the verified author-reference evaluation and both live final-day outcomes. It retains the v4 title layout.

Upload `Paper/TraceMicro_reviewed_v4_IEEE_Overleaf.zip` to a new Overleaf project. It contains the IEEE entry point at root `main.tex` and the paper inputs it uses. For ACM, upload the v4 source files with `shared/`, `figures/` and `references.bib` at the project root and select `acm/main.tex` as the Main document. Use pdfLaTeX and BibTeX.

With a local TeX distribution, run these commands from this directory:

```powershell
latexmk -pdf -halt-on-error -interaction=nonstopmode -outdir=ieee/build ieee/main.tex
latexmk -pdf -halt-on-error -interaction=nonstopmode -outdir=acm/build acm/main.tex
```

The local workspace has no working TeX compiler. Source checks cover author names, individual emails, regenerated metadata, and consistency with the v3 research content. Page counts, first-page spacing and visual layout await compilation.
