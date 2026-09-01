"""Fail when a clause anchor does not locate exactly one place in its contract.

An anchor is the gold set's claim about where a clause lives in the document. If it
matches nothing, the clause can never be covered; if it matches twice, coverage is
credited to whichever region happens to come first. Both make span coverage
meaningless, so both fail the build.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.models import ExpectedAnswer  # noqa: E402
from contract_eval.scorer import normalize_text  # noqa: E402


def main() -> int:
    failures: list[str] = []
    checked = 0
    for case in ALL_CASES:
        expected = ExpectedAnswer.model_validate(
            json.loads((ROOT / "expected" / f"{case}.json").read_text(encoding="utf-8"))
        )
        source = normalize_text((ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8"))
        for clause_type, anchor in expected.clause_anchors.items():
            occurrences = source.count(normalize_text(anchor))
            checked += 1
            if occurrences != 1:
                failures.append(
                    f"{case}.{clause_type}: anchor occurs {occurrences} times, expected 1"
                )
    if failures:
        print("\n".join(failures))
        return 1
    print(f"clause-anchor check passed: {checked} anchors, each located exactly once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
