"""Build both LaTeX entry points from the canonical manuscript and one bibliography."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def column(width, numeric=False):
    alignment = r"\raggedleft" if numeric else r"\raggedright"
    return rf">{{{alignment}\arraybackslash}}p{{{width}\linewidth}}"


LEFT = r">{\raggedright\arraybackslash}X"
TABLES = [
    ("Accepted coverage and static crossings on the 25-class scope.", "coverage",
     [LEFT, column(.10, True), column(.165), column(.08, True), column(.14, True), column(.14, True)]),
    ("Provider-reported usage and duration for the frozen original configuration.", "resources",
     [LEFT] + [column(.105, True)] * 6),
    ("Separate development attempts and reduced-context diagnostic.", "failures",
     [column(.20), LEFT, column(.08, True), column(.11), column(.20)]),
    ("Agreement with the AI-assisted author development reference.", "authoragreement",
     [LEFT, column(.12, True), column(.12, True), column(.12, True), column(.12, True), column(.14, True)]),
    ("Implementation status and unmeasured outcomes for the approved research gaps.", "gaps",
     [column(.31), LEFT, column(.33)]),
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
                      r"|Figure [12]|Table [1-5])", text)
    output = []
    for part in chunks:
        if re.fullmatch(r"\[[0-9]+\]", part):
            output.append(r"\cite{" + keys[int(part[1:-1]) - 1] + "}")
        elif part.startswith(chr(96)):
            code = part[1:-1]
            if re.fullmatch(r"[a-f0-9]{64}", code):
                output.append(r"\texttt{" + r"\allowbreak{}".join(code[i:i+16] for i in range(0, 64, 16)) + "}")
            else:
                wrapped = "".join(escape(ch) + (r"\allowbreak{}" if ch in "_/.-" else "") for ch in code)
                output.append(r"\texttt{" + wrapped + "}")
        elif re.fullmatch(r"Figure [12]", part):
            output.append(r"Figure~\ref{fig:" + FIGURES[int(part[-1])-1][0] + "}")
        elif re.fullmatch(r"Table [1-5]", part):
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
                    assert len(cells) == len(columns), label
                    rendered = [inline(cell.strip(), keys) for cell in cells]
                    if not rows:
                        rendered = [r"\textbf{" + cell + "}" for cell in rendered]
                    rows.append(" & ".join(rendered) + r" \\")
                index += 1
            output.extend([
                r"\begin{table*}[t]", r"\centering", r"\caption{" + escape(caption) + "}",
                r"\label{tab:" + label + "}", r"\setlength{\tabcolsep}{4pt}",
                r"\renewcommand{\arraystretch}{1.12}",
                r"\begin{tabularx}{\linewidth}{@{}" + "".join(columns) + "@{}}", r"\hline",
                rows[0], r"\hline", *rows[1:], r"\hline", r"\end{tabularx}", r"\end{table*}", "",
            ])
            continue
        if re.match(r"^\d+\. ", line):
            output.append(r"\begin{enumerate}")
            while index < len(lines) and re.match(r"^\d+\. ", lines[index]):
                output.append(r"\item " + inline(lines[index].split(". ", 1)[1], keys))
                index += 1
            output.append(r"\end{enumerate}")
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


def tex_metadata(front, keywords):
    title_block, *author_blocks, instructor_block = front.strip().split("\n\n")
    title, project_line = title_block.splitlines()
    project = re.fullmatch(r"Project code ([A-Z][A-Z0-9]*-\d+)", project_line)
    assert project, "Check the Markdown project code"
    assert len(author_blocks) == 3
    instructor, *affiliation = [line.rstrip() for line in instructor_block.splitlines()]
    assert instructor.startswith("Under the instruction of ")
    authors = []
    for block in author_blocks:
        name_line, roll_line, *address, email_line = [line.rstrip() for line in block.splitlines()]
        name = re.fullmatch(r"\*\*(.+)\*\*", name_line)
        roll = re.fullmatch(r"Roll number (\d{2}[a-z]-\d{4})", roll_line)
        email = re.fullmatch(r"<([^<>\s@]+@[^<>\s@]+)>", email_line)
        assert name and roll and email and address == affiliation, "Check the Markdown author blocks"
        authors.append((name[1], roll[1], email[1]))
    department, institution, location = affiliation
    city, country = location.split(", ", 1)
    institution_first, separator, institution_last = institution.partition(" of ")
    assert separator
    values = {
        "PaperTitle": title.removeprefix("# "),
        "PaperProjectCode": project[1],
        "PaperKeywords": keywords,
        "PaperLeadAuthor": authors[0][0],
        "PaperDepartment": department,
        "PaperInstitution": institution,
        "PaperInstitutionFirst": institution_first + separator.rstrip(),
        "PaperInstitutionLast": institution_last,
        "PaperCity": city,
        "PaperCountry": country,
    }
    lines = [rf"\newcommand{{\{command}}}{{{escape(value)}}}" for command, value in values.items()]
    lines.append(r"\newcommand{\PaperIEEEAuthors}{%")
    for i, (name, roll, email) in enumerate(authors):
        if i:
            lines.append(r"  \and")
        lines.extend([
            rf"  \IEEEauthorblockN{{{escape(name)}}}%",
            rf"  \IEEEauthorblockA{{Roll number {escape(roll)}\\",
            r"    \PaperDepartment\\",
            r"    \PaperInstitutionFirst\\",
            r"    \PaperInstitutionLast\\",
            r"    \PaperCity, \PaperCountry\\",
            rf"    {escape(email)}}}%",
        ])
    lines.append(r"}")
    lines.append(r"\newcommand{\PaperACMAuthors}{%")
    for name, _, email in authors:
        lines.extend([
            rf"  \author{{{escape(name)}}}%",
            r"  \affiliation{%",
            r"    \department{\PaperDepartment}%",
            r"    \institution{\PaperInstitution}%",
            r"    \city{\PaperCity}%",
            r"    \country{\PaperCountry}%",
            r"  }%",
            rf"  \email{{{escape(email)}}}%",
        ])
    lines.extend([
        r"}",
        r"\newcommand{\PaperIEEEPostAuthors}{%",
        r"  \par\smallskip",
        r"  {\normalfont\footnotesize\centering",
        r"    \textbf{Project code \PaperProjectCode}\par",
        r"    \smallskip",
        r"    " + escape(instructor).replace("Mr. ", r"Mr.\ ") + r"\\",
        r"    \PaperDepartment, \PaperInstitution, \PaperCity, \PaperCountry\par}%",
        r"  \smallskip",
        r"}",
        r"\newcommand{\PaperInstructorNote}{%",
        r"  \par\smallskip",
        r"  {\normalfont\small\centering",
        r"    " + escape(instructor).replace("Mr. ", r"Mr.\ ") + r"\\",
        r"    \PaperDepartment\\",
        r"    \PaperInstitution\\",
        r"    \PaperCity, \PaperCountry\par}%",
        r"  \smallskip",
        r"}",
    ])
    return "\n".join(lines) + "\n"


def main():
    md = (ROOT / "corrected_manuscript.md").read_text(encoding="utf-8")
    bibliography = (ROOT / "references.bib").read_text(encoding="utf-8")
    keys = re.findall(r"^@\w+\{([^,]+),", bibliography, re.M)
    front, manuscript = md.split("## Abstract\n\n", 1)
    abstract, keywords = manuscript.split("\n\n## 1. Introduction", 1)[0].split("\n\n**Keywords:** ")
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
        tex_metadata(front, keywords.rstrip(".")),
        encoding="utf-8",
    )
    print(f"Shared LaTeX generated. Abstract: {len(abstract.split())} words. Citation keys: {len(keys)}.")


if __name__ == "__main__":
    main()
