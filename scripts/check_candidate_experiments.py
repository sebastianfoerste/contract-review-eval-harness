"""Every committed candidate experiment report must reproduce byte for byte.

A report that drifts from its experiment file and attempt recordings is a number
nobody can trace. This re-aggregates each experiment directory and compares the
result with the committed JSON and Markdown, the same discipline as the live-run
report check for the v1 track.

The comparison is on the bytes of the files, so a report rewritten with other line
endings fails like one with another figure. A folder that holds a report without
the experiment file it was aggregated from fails, and so does an experiments folder
without any experiment: a check that found nothing to check has proved nothing.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.candidate_experiment import aggregate, render_markdown  # noqa: E402

EXPERIMENTS = ROOT / "candidates" / "mycounsel" / "experiments"
REPORTS = ("report.json", "report.md")


def check(experiments: Path) -> tuple[int, list[str]]:
    """Re-aggregate every experiment folder. Returns the number that reproduce and all failures."""
    failures: list[str] = []
    found = 0
    reproduced = 0
    folders = sorted(path for path in experiments.iterdir() if path.is_dir()) if experiments.is_dir() else []
    for directory in folders:
        name = directory.name
        if not (directory / "experiment.json").exists():
            orphans = [filename for filename in REPORTS if (directory / filename).exists()]
            if orphans:
                failures.append(f"{name}: holds {' and '.join(orphans)} but no experiment.json to aggregate it from")
            continue
        found += 1
        try:
            report = aggregate(directory)
        except (ValueError, OSError, KeyError) as exc:
            failures.append(f"{name}: aggregation refused: {exc}")
            continue
        expected = {
            "report.json": (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            "report.md": render_markdown(report).encode("utf-8"),
        }
        before = len(failures)
        for filename in REPORTS:
            path = directory / filename
            if not path.exists():
                failures.append(f"{name}: {filename} is missing")
            elif path.read_bytes() != expected[filename]:
                failures.append(f"{name}: {filename} differs from the current aggregation")
        reproduced += len(failures) == before
    if not found:
        failures.append(f"no experiment found under {experiments}")
    return reproduced, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiments", nargs="?", type=Path, default=EXPERIMENTS,
                        help="folder with one sub-folder per experiment; defaults to the committed experiments")
    args = parser.parse_args(argv)
    reproduced, failures = check(args.experiments)
    if failures:
        print("candidate experiment check failed:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print(f"candidate experiment check passed: {reproduced} experiment reports reproduce byte-for-byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
