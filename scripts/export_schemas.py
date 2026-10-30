"""Write, or check, the JSON Schemas for a review and an answer set.

A tool that wants to be scored targets `schemas/review-output.schema.json`; a team
scoring against its own contracts writes answer sets to
`schemas/expected-answer.schema.json`. Both are generated from the Pydantic models, so
a model change without a regenerated schema fails CI here.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from contract_eval.schemas import schema_drift, write_schemas  # noqa: E402 - needs the sys.path insert above


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the committed schemas differ from the models")
    args = parser.parse_args()
    if not args.check:
        for path in write_schemas(ROOT):
            print(f"Wrote {path.relative_to(ROOT)}")
        return 0
    drifted = schema_drift(ROOT)
    if drifted:
        print(f"JSON Schemas out of date: {', '.join(drifted)}", file=sys.stderr)
        print("Run `make schemas` and commit the diff.", file=sys.stderr)
        return 1
    print("JSON Schemas match the models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
