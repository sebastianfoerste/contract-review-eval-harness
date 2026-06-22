"""The evaluate pipeline: source -> adapter -> scorer -> scorecard."""

import argparse
import json
from pathlib import Path

from contract_eval.adapters import get_adapter
from contract_eval.models import ExpectedAnswer
from contract_eval.scorecard import render
from contract_eval.scorer import (
    citation_grounding,
    clause_scores,
    count_hallucinations,
    risk_flag_accuracy,
)


def evaluate(case: str, live: bool, out_dir: Path) -> Path:
    source = Path(f"data/{case}_sample.md").read_text()
    expected = ExpectedAnswer.model_validate(json.loads(Path(f"expected/{case}.json").read_text()))
    output = get_adapter(live).review(source_text=source, case=case)

    clause = clause_scores(expected.clause_types, [c.clause_type for c in output.clauses])
    predicted_flags = {f.clause_type: f.severity for f in output.risk_flags}
    risk_accuracy = risk_flag_accuracy(expected.risk_flags, predicted_flags)
    citation = citation_grounding(source, output.citations)
    hallucinations = count_hallucinations(source, output.citations)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "scorecard.md"
    path.write_text(render(case, clause, risk_accuracy, citation, hallucinations))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(prog="contract-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evaluate", help="score an adapter's review against the expected answers")
    ev.add_argument("--case", default="nda", help="case name (nda, saas)")
    ev.add_argument("--live", action="store_true", help="use the live Anthropic adapter instead of the stub")
    ev.add_argument("--out", default=".", type=Path, help="output directory for scorecard.md")
    args = parser.parse_args()

    if args.cmd == "evaluate":
        path = evaluate(case=args.case, live=args.live, out_dir=args.out)
        print(f"wrote {path}")
