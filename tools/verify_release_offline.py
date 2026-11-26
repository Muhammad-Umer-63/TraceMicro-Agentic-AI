"""Execute the release checks in the staged tree with Python networking blocked."""
import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
ORIGINALS = [
    "results/submit_only_live_20261122_1827/attempt_1",
    "results/reproducibility_live_20261122_1847/run_1",
    "results/reproducibility_live_20261122_1847/run_2",
]


def install_guard(denied_tree):
    runtime = Path(sys.prefix).resolve()

    def guard(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.startfile"}:
            raise PermissionError("Release check blocked networking or external execution")
        if denied_tree and event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.path.abspath(os.fsdecode(args[0])))
            if path.is_relative_to(denied_tree) and not (
                path.is_relative_to(ROOT) or path.is_relative_to(runtime)
            ):
                raise PermissionError("Release check blocked access outside the staged tree")

    sys.addaudithook(guard)


def run_script(script, *arguments):
    sys.argv = [script, *arguments]
    try:
        runpy.run_path(str(ROOT / script), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--deny-tree", type=Path, help="Optional original workspace to isolate from")
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        parser.error("Run with Python -I -B")
    deny = args.deny_tree.resolve() if args.deny_tree else None
    output = (ROOT / args.output_dir).resolve()
    output.relative_to(ROOT / "verification_outputs")
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT).as_posix()
    os.chdir(ROOT)
    # Use a new Python environment mapping. Tests inject their own synthetic values.
    os.environ = {"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
                  "TMP": str(output), "TEMP": str(output)}
    sys.path.insert(0, str(ROOT))
    install_guard(deny)
    print(f"Python {sys.version.split()[0]}, LangGraph {version('langgraph')}")
    run_script("baseline.py", "sample_petclinic", "--compare", "results/original_baseline_result.json",
               "--output", f"{relative}/package.json")
    run_script("dependency_baseline.py", "results/dependency_baseline/petclinic_raw.json", "sample_petclinic",
               "--services", "5", "--output", f"{relative}/dependency.json")
    run_script("petclinic_comparison.py", "--output", f"{relative}/three_classes.json")
    choices = [value for run in ORIGINALS for value in ("--run", run)]
    run_script("petclinic_full_scope_review.py", *choices, "--output-dir", f"{relative}/full_review")
    run_script("tools/check_langgraph_offline.py", "--output-dir", f"{relative}/offline_checks")
    loaded = {
        name: str(Path(module.__file__).resolve().relative_to(ROOT))
        for name, module in sys.modules.copy().items()
        if (name in {"baseline", "dependency_baseline", "petclinic_comparison", "petclinic_global_plan"}
            or name == "tracemicro" or name.startswith("tracemicro.")) and getattr(module, "__file__", None)
    }
    report = {"python": sys.version.split()[0], "langgraph": version("langgraph"),
              "network_blocked": True, "original_workspace_guard": deny is not None,
              "staged_imports": loaded}
    (output / "verification_environment.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
