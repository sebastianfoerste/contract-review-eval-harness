"""Compare Annotator B's returned annotations against Annotator A's, per case.

Run after B's return has been imported and its hash frozen. Produces a disagreement
ledger per case. Every row needs a written adjudication before any gold set is frozen.

    uv run python scripts/compare_annotations.py annotations/returned/annotator-b
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.adjudication import compare, render_ledger  # noqa: E402
from contract_eval.capture import text_sha256  # noqa: E402
from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.gold_v2 import ExpectedAnswerV2  # noqa: E402

DRAFTS = ROOT / "annotations" / "drafts"
LEDGERS = ROOT / "annotations" / "ledgers"


def load(path: Path, source: str) -> ExpectedAnswerV2:
    gold = ExpectedAnswerV2.model_validate(json.loads(path.read_text(encoding="utf-8")))
    gold.validate_against_source(source)
    return gold


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    returned = Path(sys.argv[1])
    if not returned.is_dir():
        print(f"not a directory: {returned}")
        return 1

    LEDGERS.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    unresolved_total = 0

    for case in ALL_CASES:
        b_path = returned / f"{case}.annotator-b.v2.json"
        if not b_path.is_file():
            print(f"{case}: no return from annotator B at {b_path}")
            return 1

        source = (ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
        a = load(DRAFTS / f"{case}.candidate.v2.json", source)
        b = load(b_path, source)

        # Freeze B's bytes before comparing, so the comparison cannot be re-run
        # against a quietly edited return.
        hashes[case] = text_sha256(b_path.read_text(encoding="utf-8"))

        report = compare(a, b)
        unresolved_total += report.unresolved()
        (LEDGERS / f"{case}.ledger.md").write_text(
            render_ledger(case, report), encoding="utf-8"
        )
        print(
            f"{case}: {len(report.matched_pairs)} matched, "
            f"{report.unresolved()} disagreements, "
            f"agreement {report.obligation_agreement:.3f}"
        )

    (LEDGERS / "annotator-b-hashes.json").write_text(
        json.dumps({"schema": "contract-review-eval.annotation-return.v1",
                    "sha256": hashes}, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\ntotal unresolved disagreements: {unresolved_total}")
    if unresolved_total:
        print("Gold cannot be frozen until every one carries a written adjudication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
