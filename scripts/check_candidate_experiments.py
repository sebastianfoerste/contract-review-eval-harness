"""Every committed candidate experiment report must reproduce byte for byte.

A report that drifts from its experiment file and attempt recordings is a number
nobody can trace. This re-aggregates each experiment directory and compares the
result with the committed JSON and Markdown, the same discipline as the live-run
report check for the v1 track.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.candidate_experiment import aggregate, render_markdown  # noqa: E402

EXPERIMENTS = ROOT / "candidates" / "mycounsel" / "experiments"


def main() -> int:
    failures: list[str] = []
    checked = 0
    for experiment_file in sorted(EXPERIMENTS.glob("*/experiment.json")):
        directory = experiment_file.parent
        name = directory.name
        try:
            report = aggregate(directory)
        except ValueError as exc:
            failures.append(f"{name}: aggregation refused: {exc}")
            continue
        expected_json = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        for filename, expected in (("report.json", expected_json), ("report.md", render_markdown(report))):
            path = directory / filename
            if not path.exists():
                failures.append(f"{name}: {filename} is missing")
            elif path.read_text(encoding="utf-8") != expected:
                failures.append(f"{name}: {filename} differs from the current aggregation")
        checked += 1
    if failures:
        print("candidate experiment check failed:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print(f"candidate experiment check passed: {checked} experiment reports reproduce byte-for-byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
