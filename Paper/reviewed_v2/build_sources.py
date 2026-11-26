"""Build both LaTeX entry points from the canonical manuscript and one bibliography."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
TABLES = [
    ("Accepted coverage and static crossings on the 25-class scope.", "coverage",
     r"@{}p{.25\textwidth}rp{.21\textwidth}rrr@{}"),
    ("Provider-reported usage and duration for the frozen original configuration.", "resources",
     r"@{}lrrrrrr@{}"),
    ("Separate development attempts and reduced-context diagnostic.", "failures",
     r"@{}p{.18\textwidth}p{.28\textwidth}rp{.14\textwidth}p{.22\textwidth}@{}"),
    ("Implementation status and unmeasured outcomes for the approved research gaps.", "gaps",
     r"@{}p{.30\textwidth}p{.26\textwidth}p{.35\textwidth}@{}"),
]
FIGURES = [
    ("architecture", "Implemented workflow paths and the status of optional components.",
     "Evidence feeds either the interactive pilot or the original batch path. Both use Groq and LangGraph and save assignments and traces. Full v3 planning, criticism and runtime masks have fixture evidence."),
    ("group_sizes", "Nonempty group sizes on the same 25 classes. Each original run has the same single group.",
     "Package groups have sizes 11, 5, 4, 3, and 2. Dependency groups have sizes 21, 1, 1, 1, and 1. Each original live run has one group of size 25."),
]
ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "–": "--", "—": "---", "’": "'", "“": chr(96) * 2, "”": "''",
}


def escape(text):
    return "".join(ESCAPES.get(character, character) for character in text)


def inline(text, keys):
    chunks = re.split(r"(\[[0-9]+\]|" + chr(96) + r"[^" + chr(96) + r"]+" + chr(96) +
                      r"|Figure [12]|Table [1-4])", text)
    output = []
    for part in chunks:
        if re.fullmatch(r"\[[0-9]+\]", part):
            output.append(r"\cite{" + keys[int(part[1:-1]) - 1] + "}")
        elif part.startswith(chr(96)):
            code = part[1:-1]
            if re.fullmatch(r"[a-f0-9]{64}", code):
                output.append(r"\texttt{" + r"\allowbreak{}".join(code[i:i+16] for i in range(0, 64, 16)) + "}")
            else:
                output.append(r"\texttt{" + escape(code) + "}")
        elif re.fullmatch(r"Figure [12]", part):
            output.append(r"Figure~\ref{fig:" + FIGURES[int(part[-1])-1][0] + "}")
        elif re.fullmatch(r"Table [1-4]", part):
            output.append(r"Table~\ref{tab:" + TABLES[int(part[-1])-1][1] + "}")
        else:
            output.append("".join(r"\textbf{" + escape(word) + "}" if i % 2 else escape(word)
                                  for i, word in enumerate(part.split("**"))))
    return "".join(output)


def tex_body(lines, keys):
    output = []
    table_index = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("|"):
            caption, label, columns = TABLES[table_index]
            table_index += 1
            rows = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = lines[index].strip("|").split("|")
                if not all(re.fullmatch(r"\s*:?-+:?\s*", cell) for cell in cells):
                    rows.append(" & ".join(inline(cell.strip(), keys) for cell in cells) + r" \\")
                index += 1
            output.extend([
                r"\begin{table*}[t]", r"\centering", r"\caption{" + escape(caption) + "}",
                r"\label{tab:" + label + "}", r"\begin{tabular}{" + columns + "}", r"\hline",
                rows[0], r"\hline", *rows[1:], r"\hline", r"\end{tabular}", r"\end{table*}", "",
            ])
            continue
        if line.startswith("!["):
            name = Path(line.split("](")[1].removesuffix(")")).stem
            _, caption, description = next(fig for fig in FIGURES if fig[0] == name)
            output.extend([
                r"\begin{figure}[t]", r"\centering", r"\input{figures/" + name + "}",
                r"\caption{" + escape(caption) + "}", r"\label{fig:" + name + "}",
                r"\Description{" + escape(description) + "}", r"\end{figure}", "",
            ])
        elif line.startswith("##"):
            marker, heading = line.split(" ", 1)
            heading = re.sub(r"^[0-9.]+\.? ", "", heading)
            command = "section" if marker == "##" else "subsection"
            output.append("\\" + command + "{" + escape(heading) + "}")
        else:
            output.append(inline(line, keys))
        index += 1
    assert table_index == len(TABLES)
    return "\n".join(output).rstrip() + "\n"


def main():
    md = (ROOT / "corrected_manuscript.md").read_text(encoding="utf-8")
    bibliography = (ROOT / "references.bib").read_text(encoding="utf-8")
    keys = re.findall(r"^@\w+\{([^,]+),", bibliography, re.M)
    title = md.splitlines()[0].removeprefix("# ")
    project = re.search(r"^\*\*Project code:\*\* (.+)$", md, re.M)[1]
    abstract, keywords = md.split("## Abstract\n\n")[1].split("\n\n## 1. Introduction", 1)[0].split("\n\n**Keywords:** ")
    body, references = md[md.index("## 1. Introduction"):].split("\n## References\n")
    assert 150 <= len(abstract.split()) <= 250
    cited = {int(c) for c in re.findall(r"\[([0-9]+)\]", body)}
    assert cited == set(range(1, len(keys)+1))
    assert re.findall(r"^\[([0-9]+)\]", references, re.M) == list(map(str, range(1, len(keys)+1)))
    links = re.findall(r"^\s*url = \{([^}]+)\}", bibliography, re.M)
    assert all(link in references for link in links)
    for name, _, _ in FIGURES:
        assert (ROOT / "figures" / (name + ".tex")).is_file()
        assert (ROOT / "figures" / (name + ".svg")).is_file()

    shared = ROOT / "shared"
    shared.mkdir(exist_ok=True)
    (shared / "body.tex").write_text(tex_body(body.splitlines(), keys), encoding="utf-8")
    (shared / "abstract.tex").write_text(inline(abstract, keys) + "\n", encoding="utf-8")
    (shared / "metadata.tex").write_text(
        "\\newcommand{\\PaperTitle}{" + escape(title) + "}\n"
        "\\newcommand{\\PaperKeywords}{" + escape(keywords.rstrip(".")) + "}\n"
        "\\newcommand{\\ProjectCode}{" + escape(project) + "}\n",
        encoding="utf-8",
    )
    print(f"Shared LaTeX generated. Abstract: {len(abstract.split())} words. Citation keys: {len(keys)}.")


if __name__ == "__main__":
    main()
