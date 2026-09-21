"""Compatibility entrypoint for immutable second-annotation intake.

Use contract-eval reference-prepare to create editable adjudication templates.
Re-running this command never replaces an earlier return or its hashes.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from contract_eval.reference_evidence import import_returns


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: compare_annotations.py RETURNED_DIRECTORY", file=sys.stderr)
        return 2
    try:
        receipt = import_returns(ROOT, Path(sys.argv[1]))
        for row in receipt["cases"]:
            print(f"{row['case']}: {row['disagreements']} disagreements; original bytes retained")
        print("Evidence saved in annotations/reference-evidence/imported. Written adjudication remains required.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Reference evidence error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
