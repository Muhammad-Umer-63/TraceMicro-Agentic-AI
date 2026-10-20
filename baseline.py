import argparse
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser(
    description="Preliminary package-based Java decomposition baseline"
)
parser.add_argument("repository", help="Path to an extracted Java repository")
args = parser.parse_args()

root = Path(args.repository).resolve()
source_root = root / "src" / "main" / "java"

if not source_root.is_dir():
    raise SystemExit(f"Java source folder not found: {source_root}")

services = {}
unassigned = []
inventory = []

for path in sorted(source_root.rglob("*.java")):
    if path.name in {"package-info.java", "module-info.java"}:
        continue

    relative = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    # Remove comments before looking for a package declaration.
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    match = re.search(
        r"^\s*package\s+([\w.]+)\s*;", text, flags=re.M
    )

    inventory.append(relative)
    if match:
        services.setdefault(match.group(1), []).append(relative)
    else:
        unassigned.append(relative)

total = len(inventory)
if total == 0:
    raise SystemExit("No eligible Java source files found.")

assigned = sum(len(files) for files in services.values())

result = {
    "baseline": "package-based grouping",
    "unit": "Java source file",
    "state": {
        "status": "completed",
        "files_discovered": total,
        "files_assigned": assigned,
        "assignment_coverage": assigned / total,
        "candidate_service_count": len(services),
        "unassigned_files": unassigned,
    },
    "source_inventory": inventory,
    "candidate_services": services,
    "limitations": [
        "Package boundaries are only preliminary service candidates.",
        "No semantic, dependency, runtime, or database analysis.",
        "No LLM or agent integration.",
        "Coverage does not measure decomposition correctness.",
    ],
}

output = Path("results")
output.mkdir(exist_ok=True)
target = output / "baseline_result.json"
target.write_text(json.dumps(result, indent=2), encoding="utf-8")

print(json.dumps(result["state"], indent=2))
print(f"Saved: {target}")
