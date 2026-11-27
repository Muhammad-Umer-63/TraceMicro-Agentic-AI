"""Generate matching SVG previews and native TikZ artwork without dependencies."""
from html import escape
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PALETTE = ["#215674", "#326987", "#57849b", "#7b9bad", "#a6bfc9"]
INK = "#172e3b"


class Figure:
    def __init__(self, name, width, height, description):
        self.name = name
        self.svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
            f"<title>{escape(description)}</title>",
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
            f'<path d="M0,0 L7,3 L0,6 Z" fill="{INK}"/></marker></defs>',
        ]
        self.tex = [
            r"\begin{tikzpicture}[x=0.56pt,y=-0.56pt, every node/.style={font=\sffamily\footnotesize,inner sep=1pt}]",
            rf"\path[use as bounding box] (0,0) rectangle ({width},{height});",
        ]

    @staticmethod
    def color(color):
        rgb = [int(color[i:i+2], 16) for i in (1, 3, 5)]
        return "{rgb,255:red,%d;green,%d;blue,%d}" % tuple(rgb)

    def line(self, x, y, xx, yy, arrow=False, dashed=False):
        style = (" marker-end=\"url(#arrow)\"" if arrow else "") + (' stroke-dasharray="4 3"' if dashed else "")
        self.svg.append(f'<line x1="{x}" y1="{y}" x2="{xx}" y2="{yy}" stroke="{INK}" stroke-width="1.5"{style}/>')
        options = ["draw=" + self.color(INK), "line width=0.6pt"]
        if arrow:
            options.append("->")
        if dashed:
            options.append("dashed")
        self.tex.append(rf"\draw[{','.join(options)}] ({x},{y}) -- ({xx},{yy});")

    def rect(self, x, y, w, h, fill, dashed=False):
        style = ' stroke-dasharray="4 3"' if dashed else ''
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{INK}"{style}/>')
        options = ",dashed" if dashed else ""
        self.tex.append(rf"\draw[draw={self.color(INK)},fill={self.color(fill)}{options}] ({x},{y}) rectangle ({x+w},{y+h});")

    def label(self, x, y, text, white=False):
        color = "#ffffff" if white else INK
        self.svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="sans-serif" '
                        f'font-size="14" text-anchor="middle" dominant-baseline="central">{escape(text)}</text>')
        safe = text.replace("&", r"\&")
        self.tex.append(rf"\node[text={self.color(color)}] at ({x},{y}) {{{safe}}};")

    def box(self, x, y, w, lines, dashed=False):
        self.rect(x, y, w, 49, "#f5f8fa" if dashed else "#e3edf2", dashed)
        for i, line in enumerate(lines):
            self.label(x + w / 2, y + 15 + i * 19, line)

    def save(self):
        (HERE / (self.name + ".svg")).write_text("\n".join([*self.svg, "</svg>"]) + "\n", encoding="utf-8")
        (HERE / (self.name + ".tex")).write_text("\n".join([*self.tex, r"\end{tikzpicture}"]) + "\n", encoding="utf-8")


def architecture():
    f = Figure("architecture", 429, 356, "TraceMicro paths and their evidence status")
    f.box(35, 4, 359, ("Java source + saved static analyzer export", "Evidence store with source and relation IDs"))
    for x in (108, 322):
        f.line(x, 53, x, 79, arrow=True)
    f.box(4, 79, 207, ("Interactive pilot (live)", "Model requests local tools"))
    f.box(218, 79, 207, ("Full scope (live original)", "Precollect, then nine batches"))
    for x in (108, 322):
        f.line(x, 128, x, 150, arrow=True)
    f.box(35, 150, 359, ("LangGraph routes decisions and validation", "Groq responses + deterministic local checks"))
    f.line(215, 199, 215, 221, arrow=True)
    f.box(35, 221, 359, ("Accepted or incomplete assignments", "Saved traces, findings and usage"))
    f.line(215, 270, 215, 293, dashed=True)
    f.box(4, 293, 421, ("Full v3 planner, critic and runtime masks", "Fixture evidence for these paths"), dashed=True)
    f.save()


def group_sizes():
    graph = json.loads((ROOT / "results/dependency_baseline/petclinic_k5.json").read_text(encoding="utf-8"))
    runs = [
        "submit_only_live_20261122_1827/attempt_1",
        "reproducibility_live_20261122_1847/run_1",
        "reproducibility_live_20261122_1847/run_2",
    ]
    for run in runs:
        data = json.loads((ROOT / "results" / run / "summary.json").read_text(encoding="utf-8"))
        assert len(data["accepted_assignments"]) == 25
        assert all(row["services"] == ["candidate_1"] and not row["shared"] for row in data["accepted_assignments"])
    f = Figure("group_sizes", 429, 166, "Group sizes across three complete 25-class conditions")
    f.label(277, 14, "Classes in each nonempty group")
    for y, name, sizes in zip(
        (29, 67, 105),
        ("Package", "Dependency", "Original (3 runs)"),
        (graph["package_structure"]["group_sizes"], graph["graph_structure"]["group_sizes"], [25]),
    ):
        f.label(63, y + 13, name)
        x = 142
        for i, size in enumerate(sizes):
            width = size * 11
            f.rect(x, y, width, 26, PALETTE[i])
            f.label(x + width / 2, y + 13, str(size), white=i < 2)
            x += width
    f.label(276, 148, "Each row covers the same 25 classes")
    f.save()


if __name__ == "__main__":
    architecture()
    group_sizes()
