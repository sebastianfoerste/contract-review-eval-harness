"""The evaluate pipeline: source -> adapter -> scorer -> scorecard."""

import argparse
import datetime
import json
import sys
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


def evaluate_case(case: str, live: bool) -> dict:
    source = Path(f"data/{case}_sample.md").read_text()
    expected = ExpectedAnswer.model_validate(json.loads(Path(f"expected/{case}.json").read_text()))
    output = get_adapter(live).review(source_text=source, case=case)

    clause = clause_scores(expected.clause_types, [c.clause_type for c in output.clauses])
    predicted_flags = {f.clause_type: f.severity for f in output.risk_flags}
    risk_accuracy = risk_flag_accuracy(expected.risk_flags, predicted_flags)
    citation = citation_grounding(source, output.citations)
    hallucinations = count_hallucinations(source, output.citations)

    # Base thresholds matching the stub adapter baseline
    thresholds = {
        "f1": 0.85,
        "risk_accuracy": 0.45,
        "grounding_rate": 0.75,
        "hallucinations": 1.0,
    }
    if expected.thresholds:
        thresholds.update(expected.thresholds)

    return {
        "clause_precision": clause.precision,
        "clause_recall": clause.recall,
        "clause_f1": clause.f1,
        "risk_flag_accuracy": risk_accuracy,
        "citation_grounding": citation.grounding_rate,
        "hallucination_count": hallucinations,
        "thresholds": thresholds,
    }


def render_multi(scores: dict) -> str:
    parts = ["# Contract Review Eval Scorecard — ALL CASES\n"]
    for case, s in scores.items():
        parts.append(f"## Case: {case}")
        parts.append(
            f"| Dimension | Score | Notes |\n"
            f"|---|---:|---|\n"
            f"| Clause precision | {s['clause_precision']:.2f} | predicted clause types that were expected |\n"
            f"| Clause recall | {s['clause_recall']:.2f} | expected clause types that were found |\n"
            f"| Clause F1 | {s['clause_f1']:.2f} | harmonic mean of precision and recall |\n"
            f"| Risk-flag accuracy | {s['risk_flag_accuracy']:.2f} | risky clauses flagged at the expected severity |\n"
            f"| Citation grounding | {s['citation_grounding']:.2f} | quotes found in the source |\n"
            f"| Hallucination count | {s['hallucination_count']} | cited quotes not present in the source |\n"
        )
    return "\n".join(parts)


def evaluate(case: str, live: bool, out_dir: Path, no_gate: bool = False, format_type: str = "markdown") -> Path:
    cases_to_eval = ["nda", "saas"] if case == "all" else [case]
    run_scores = {}

    for c in cases_to_eval:
        run_scores[c] = evaluate_case(c, live)

    out_dir.mkdir(parents=True, exist_ok=True)

    if format_type == "json":
        path = out_dir / "scorecard.json"
        path.write_text(json.dumps({"case": case, "scores": run_scores}, indent=2))
    else:
        path = out_dir / "scorecard.md"
        if case == "all":
            path.write_text(render_multi(run_scores))
        else:
            s = run_scores[case]
            # Reconstruct score structures for existing render method
            from contract_eval.scorer import CitationScore, ClauseScore
            clause = ClauseScore(s["clause_precision"], s["clause_recall"], s["clause_f1"])
            citation = CitationScore(0, 0, s["citation_grounding"]) # render only displays the rate
            path.write_text(render(case, clause, s["risk_flag_accuracy"], citation, s["hallucination_count"]))

    # Save run to history
    history_dir = Path("history")
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    history_file = history_dir / f"run_{timestamp}.json"
    history_file.write_text(json.dumps({
        "timestamp": datetime.datetime.now().isoformat(),
        "case": case,
        "scores": run_scores
    }, indent=2))

    # Gating checks (only enforce if not bypassed)
    if not no_gate:
        violations = []
        for c in cases_to_eval:
            s = run_scores[c]
            t = s["thresholds"]
            if s["clause_f1"] < t["f1"]:
                violations.append(f"[{c.upper()}] Clause F1 score {s['clause_f1']:.2f} is below threshold {t['f1']:.2f}")
            if s["risk_flag_accuracy"] < t["risk_accuracy"]:
                violations.append(f"[{c.upper()}] Risk-flag accuracy {s['risk_flag_accuracy']:.2f} is below threshold {t['risk_accuracy']:.2f}")
            if s["citation_grounding"] < t["grounding_rate"]:
                violations.append(f"[{c.upper()}] Citation grounding rate {s['citation_grounding']:.2f} is below threshold {t['grounding_rate']:.2f}")
            if float(s["hallucination_count"]) > t["hallucinations"]:
                violations.append(f"[{c.upper()}] Hallucination count {s['hallucination_count']} is above threshold {t['hallucinations']:.0f}")

        if violations:
            print("\n=== EVALUATION QUALITY GATE FAILED ===")
            for v in violations:
                print(f"- {v}")
            print("======================================")
            raise ValueError("Evaluation did not meet the required quality thresholds.")

    return path


def compare_runs(history_dir: Path = Path("history")) -> None:
    if not history_dir.exists():
        print("No history directory found. Run evaluate first to create history.")
        sys.exit(1)

    run_files = sorted(history_dir.glob("run_*.json"), key=lambda f: f.name)
    if not run_files:
        print("No previous run history files found. Run evaluate first.")
        sys.exit(1)

    latest_file = run_files[-1]
    print(f"Comparing current scores against historical run: {latest_file.name}")

    latest_data = json.loads(latest_file.read_text())
    past_case = latest_data["case"]
    past_scores = latest_data["scores"]

    cases_to_eval = ["nda", "saas"] if past_case == "all" else [past_case]

    current_scores = {}
    for c in cases_to_eval:
        current_scores[c] = evaluate_case(c, live=False)

    print("\n================== REGRESSION COMPARISON ==================")
    print(f"{'Dimension':<25} | {'Past':<10} | {'Current':<10} | {'Delta':<10}")
    print("-" * 65)

    regressed = False
    for c in cases_to_eval:
        print(f"\nCase: {c.upper()}")
        p_sc = past_scores[c]
        c_sc = current_scores[c]

        metrics = [
            ("Clause Precision", "clause_precision"),
            ("Clause Recall", "clause_recall"),
            ("Clause F1", "clause_f1"),
            ("Risk Flag Accuracy", "risk_flag_accuracy"),
            ("Citation Grounding", "citation_grounding"),
            ("Hallucinations", "hallucination_count")
        ]

        for name, key in metrics:
            past_val = p_sc[key]
            curr_val = c_sc[key]
            delta = curr_val - past_val

            is_worse = (delta < 0) if key != "hallucination_count" else (delta > 0)
            delta_str = f"{delta:+.2f}" if delta != 0 else "0.00"
            if is_worse:
                delta_str += " ⚠️"
                regressed = True

            print(f"{name:<25} | {past_val:<10.2f} | {curr_val:<10.2f} | {delta_str:<10}")

    print("===========================================================")
    if regressed:
        print("\nWarning: Performance regression detected relative to the previous run.")
    else:
        print("\nSuccess: No regressions detected!")


def main() -> None:
    parser = argparse.ArgumentParser(prog="contract-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    
    ev = sub.add_parser("evaluate", help="score an adapter's review against the expected answers")
    ev.add_argument("--case", default="nda", help="case name (nda, saas, all)")
    ev.add_argument("--live", action="store_true", help="use the live adapter instead of the stub")
    ev.add_argument("--out", default=".", type=Path, help="output directory for scorecard.md")
    ev.add_argument("--no-gate", action="store_true", help="do not exit with code 1 on regression/failure")
    ev.add_argument("--format", default="markdown", choices=["markdown", "json"], help="output format (markdown, json)")
    
    sub.add_parser("compare", help="compare the current scores against the latest saved run in history")
    
    args = parser.parse_args()

    if args.cmd == "evaluate":
        try:
            path = evaluate(case=args.case, live=args.live, out_dir=args.out, no_gate=args.no_gate, format_type=args.format)
            print(f"wrote {path}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    elif args.cmd == "compare":
        compare_runs()


if __name__ == "__main__":
    main()
