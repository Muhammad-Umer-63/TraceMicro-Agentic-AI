# TraceMicro

TraceMicro investigates agentic support for decomposing Java monoliths into candidate microservices.

## Current implementation

Two deterministic, non-agentic baselines are available:

- baseline.py groups Java source files by package.
- dependency_baseline.py clusters classes using saved output from the official MicroAgent dependency analyzer.

Model integration, agent workflows, and reference-based evaluation are not yet implemented.

## Requirements

Python 3.10 or newer. No external Python packages are needed for the Python baselines and tests.

## Commands

Package baseline:
    python baseline.py sample_petclinic --output results/package_run.json

Dependency baseline using saved analyzer output:
    python dependency_baseline.py results/dependency_baseline/petclinic_raw.json sample_petclinic --services 5 --output results/dependency_run.json

Tests:
    python -m unittest discover -s tests -v

Re-running Java dependency extraction requires the separately obtained MicroAgent analyzer and its dependencies.

## Results and limitations

The sample contains 25 eligible Java files. Package grouping produced five groups of sizes 11, 5, 4, 3, 2. The dependency baseline produced groups of sizes 21, 1, 1, 1, 1. Five groups was an experimental setting chosen to match the package count.

These results do not establish architectural accuracy. The analyzer may silently omit malformed files or unresolved references. See docs/DEPENDENCY_BASELINE_REVIEW.md for details.

The PetClinic source subset retains its original license. The analyzer comes from the MicroAgent authors' artifact: https://doi.org/10.5281/zenodo.19250602

The exact upstream revision of the supplied PetClinic snapshot remains unknown.
