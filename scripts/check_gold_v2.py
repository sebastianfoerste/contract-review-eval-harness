"""Validate the candidate v2 obligation sets against their source documents."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.gold_v2 import ExpectedAnswerV2  # noqa: E402

DRAFTS = ROOT / "annotations" / "drafts"


def main() -> int:
    failures: list[str] = []
    total = 0

    for case in ALL_CASES:
        path = DRAFTS / f"{case}.candidate.v2.json"
        if not path.is_file():
            failures.append(f"{case}: missing {path.relative_to(ROOT)}")
            continue
        try:
            gold = ExpectedAnswerV2.model_validate(json.loads(path.read_text(encoding="utf-8")))
            source = (ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
            gold.validate_against_source(source)
        except Exception as exc:
            failures.append(f"{case}: {exc}")
            continue
        total += len(gold.obligations)

    if failures:
        print("\n".join(failures))
        return 1
    print(f"gold v2 check passed: {total} candidate obligations, every offset resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
