"""The evaluate pipeline: source -> adapter -> scorer -> scorecard."""

import argparse
import datetime
import json
import sys
from pathlib import Path

from contract_eval.adapters import adapter_identifier, get_adapter
from contract_eval.cases import ALL_CASES
from contract_eval.models import ExpectedAnswer, ReviewOutput
from contract_eval.provenance import run_provenance, write_provenance
from contract_eval.scorecard import render
from contract_eval.release_certificate import (
    build_release_certificate,
    render_release_certificate,
    verify_release_certificate,
)
from contract_eval.scorer import (
    citation_grounding,
    clause_scores,
    count_hallucinations,
    risk_flag_accuracy,
    risk_metrics,
    span_coverage,
)
from contract_eval.robustness import (
    build_robustness_report,
    verify_robustness_report,
    write_robustness_report,
)


def canonical_clause(clause_type: str, aliases: dict[str, str]) -> str:
    """Map a declared synonym onto the gold set's own name for the same clause.

    Adapters name clauses in their own vocabulary: `no_licence` for `no_license`,
    `sub_processors` for `subprocessors`, `permitted_disclosures` for the singular.
    Scoring those as missed clauses measures vocabulary, not legal judgment, and
    quietly reports a correct review as a failure. Aliases are declared in the gold
    set so the mapping is reviewable.
    """
    return aliases.get(clause_type, clause_type)


def canonicalise_risk_flags(
    risk_flags: list,
    aliases: dict[str, str],
) -> tuple[dict[str, str], list[str], list[str]]:
    """Collapse predicted flags onto canonical clause names, visibly.

    A dict comprehension silently kept the last flag whenever two predictions
    canonicalised onto the same clause, so a review flagging `sub_processors` high
    and `subprocessors` low scored as whichever came second. Duplicates are now
    reported, and a duplicate carrying a different severity is a conflict: the
    review contradicts itself about one clause and cannot be treated as agreeing
    with the gold set.
    """
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    conflicts: list[str] = []
    for flag in risk_flags:
        canonical = canonical_clause(flag.clause_type, aliases)
        if canonical in seen:
            duplicates.append(canonical)
            if seen[canonical] != flag.severity:
                conflicts.append(canonical)
            continue
        seen[canonical] = flag.severity
    return seen, sorted(set(duplicates)), sorted(set(conflicts))


def score_review(
    source_text: str,
    expected: ExpectedAnswer,
    output: ReviewOutput,
    *,
    alias_mode: str = "on",
) -> dict:
    """Score one review. Pure: no file access, no network, no adapter.

    Extracted so a live evaluation and an offline replay of the same captured bytes
    run through identical code. If replay had its own scoring path, a replayed score
    would prove nothing about the published one.

    `alias_mode` selects whether declared clause synonyms are applied, which is what
    makes the aliases-off and aliases-on comparison a controlled experiment rather
    than two different scorers.
    """
    if alias_mode not in ("on", "off"):
        raise ValueError(f"alias_mode must be 'on' or 'off', got {alias_mode!r}")
    aliases = expected.clause_aliases if alias_mode == "on" else {}
    source = source_text
    clause = clause_scores(
        expected.clause_types,
        [canonical_clause(c.clause_type, aliases) for c in output.clauses],
    )
    predicted_flags, duplicate_flags, conflicting_flags = canonicalise_risk_flags(
        output.risk_flags, aliases
    )
    risk_accuracy = risk_flag_accuracy(expected.risk_flags, predicted_flags)
    risk = risk_metrics(expected.risk_flags, predicted_flags)
    citation = citation_grounding(source, output.citations)
    hallucinations = count_hallucinations(source, output.citations)
    coverage = span_coverage(source, expected.clause_anchors, output.citations)

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
        "risk_precision": risk.precision,
        "risk_recall": risk.recall,
        "risk_f1": risk.f1,
        "risk_severity_accuracy": risk.severity_accuracy,
        "risk_false_positives": risk.false_positives,
        "risk_missed": risk.missed,
        "risk_severity_confusion": risk.severity_confusion,
        "risk_duplicate_flags": duplicate_flags,
        "risk_conflicting_flags": conflicting_flags,
        "span_coverage": coverage.coverage,
        "span_uncovered_clauses": coverage.uncovered,
        "citation_grounded": citation.grounded,
        "citation_total": citation.total,
        "citation_grounding": citation.grounding_rate,
        "hallucination_count": hallucinations,
        "thresholds": thresholds,
    }


def load_case_inputs(case: str, root: Path = Path(".")) -> tuple[str, ExpectedAnswer]:
    source = (root / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
    expected = ExpectedAnswer.model_validate(
        json.loads((root / "expected" / f"{case}.json").read_text(encoding="utf-8"))
    )
    return source, expected


def evaluate_case(case: str, live: bool, model: str | None = None) -> dict:
    """Produce and score one review through the adapter."""
    source, expected = load_case_inputs(case)
    output = get_adapter(live, model=model).review(source_text=source, case=case)
    return score_review(source, expected, output, alias_mode="on")


def render_multi(scores: dict) -> str:
    parts = ["# Contract Review Eval Scorecard: ALL CASES\n"]
    for case, s in scores.items():
        parts.append(f"## Case: {case}")
        parts.append(
            f"| Dimension | Score | Notes |\n"
            f"|---|---:|---|\n"
            f"| Clause precision | {s['clause_precision']:.2f} | predicted clause types that were expected |\n"
            f"| Clause recall | {s['clause_recall']:.2f} | expected clause types that were found |\n"
            f"| Clause F1 | {s['clause_f1']:.2f} | harmonic mean of precision and recall |\n"
            f"| Risk precision | {s['risk_precision']:.2f} | flagged clauses that the gold set treats as risks |\n"
            f"| Risk recall | {s['risk_recall']:.2f} | gold risks the review flagged |\n"
            f"| Risk F1 | {s['risk_f1']:.2f} | harmonic mean of risk precision and recall |\n"
            f"| Severity accuracy | {s['risk_severity_accuracy']:.2f} | correct severity among jointly identified risks |\n"
            f"| Risk false positives | {len(s['risk_false_positives'])} | clauses flagged that the gold set does not treat as risks |\n"
            f"| Risk missed | {len(s['risk_missed'])} | gold risks the review did not flag |\n"
            f"| Duplicate / conflicting flags | {len(s['risk_duplicate_flags'])} / {len(s['risk_conflicting_flags'])} | predictions collapsing onto one clause |\n"
            f"| Span coverage | {s['span_coverage']:.2f} | gold clauses with a grounded citation inside them |\n"
            f"| Risk-flag accuracy (legacy) | {s['risk_flag_accuracy']:.2f} | blind to false positives; excluded from release decisions |\n"
            f"| Citation grounding | {s['citation_grounding']:.2f} | {s['citation_grounded']}/{s['citation_total']} quotes matched as an exact span of the normalised source |\n"
            f"| Hallucination count | {s['hallucination_count']} | cited quotes not grounded in the source |\n"
        )
    return "\n".join(parts)


def evaluate(case: str, live: bool, out_dir: Path, no_gate: bool = False, format_type: str = "markdown", model: str | None = None) -> Path:
    cases_to_eval = ALL_CASES if case == "all" else [case]
    run_scores = {}

    for c in cases_to_eval:
        run_scores[c] = evaluate_case(c, live, model=model)

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
            citation = CitationScore(s["citation_grounded"], s["citation_total"], s["citation_grounding"])
            path.write_text(
                render(
                    case, clause, s["risk_flag_accuracy"], citation,
                    s["hallucination_count"], scores=s,
                )
            )

    provenance = run_provenance(
        tuple(cases_to_eval),
        adapter=adapter_identifier(live, model),
        # The adapter produced this output during this call, so the two dates
        # coincide here. Re-scoring a stored output must set them apart.
        output_generated_at=datetime.datetime.now().isoformat(timespec="seconds"),
        scored_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    write_provenance(provenance, out_dir / "run-provenance.json")

    # Save run to history
    history_dir = Path("history")
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    history_file = history_dir / f"run_{timestamp}.json"
    history_file.write_text(json.dumps({
        "timestamp": datetime.datetime.now().isoformat(),
        "case": case,
        "provenance": provenance,
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
            print("\n=== demo-regression-policy.v2 GATE FAILED ===")
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

    cases_to_eval = ALL_CASES if past_case == "all" else [past_case]

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


def certify(case: str, out_dir: Path) -> tuple[Path, Path]:
    cases_to_eval = ALL_CASES if case == "all" else [case]
    certificate = build_release_certificate(
        {name: evaluate_case(name, live=False) for name in cases_to_eval}
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "release-certificate.json"
    markdown_path = out_dir / "release-certificate.md"
    json_path.write_text(json.dumps(certificate, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(
        render_release_certificate(certificate),
        encoding="utf-8",
    )
    return markdown_path, json_path


def verify_certificate(certificate_path: Path) -> dict:
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    scores = {
        case: evaluate_case(case, live=False)
        for case in ALL_CASES
    }
    return verify_release_certificate(certificate, scores)


def robustness(
    campaign_path: Path,
    out_dir: Path,
    *,
    live: bool,
    runs: int,
    model: str | None = None,
) -> dict:
    scores = {
        case: evaluate_case(case, live=False)
        for case in ALL_CASES
    }
    certificate = build_release_certificate(scores)
    report = build_robustness_report(
        campaign_path,
        get_adapter(live, model=model),
        certificate,
        runs=runs,
    )
    write_robustness_report(report, out_dir)
    return report


def verify_robustness(
    report_path: Path,
    campaign_path: Path,
) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    scores = {
        case: evaluate_case(case, live=False)
        for case in ALL_CASES
    }
    expected = build_robustness_report(
        campaign_path,
        get_adapter(False),
        build_release_certificate(scores),
    )
    return verify_robustness_report(report, expected)


def main() -> None:
    parser = argparse.ArgumentParser(prog="contract-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    
    ev = sub.add_parser("evaluate", help="score an adapter's review against the expected answers")
    ev.add_argument("--case", default="nda", help="case name (nda, saas, all)")
    ev.add_argument("--live", action="store_true", help="use the live adapter instead of the stub")
    ev.add_argument(
        "--model",
        default=None,
        help="model id for --live (default: CONTRACT_EVAL_MODEL, else claude-opus-5)",
    )
    ev.add_argument("--out", default=".", type=Path, help="output directory for scorecard.md")
    ev.add_argument("--no-gate", action="store_true", help="do not exit with code 1 on regression/failure")
    ev.add_argument("--format", default="markdown", choices=["markdown", "json"], help="output format (markdown, json)")
    
    sub.add_parser("compare", help="compare the current scores against the latest saved run in history")
    cert = sub.add_parser(
        "certify",
        help="issue an input-bound release decision over the synthetic benchmark suite",
    )
    cert.add_argument("--case", default="all", help="case name (nda, saas, all)")
    cert.add_argument("--out", default="examples", type=Path, help="certificate output directory")
    verify = sub.add_parser(
        "verify-certificate",
        help="re-run the offline benchmark and verify a release certificate",
    )
    verify.add_argument(
        "--certificate",
        default="examples/release-certificate.json",
        type=Path,
        help="release certificate JSON to verify",
    )
    robust = sub.add_parser(
        "robustness",
        help="run the adversarial minimal-pair contract review campaign",
    )
    robust.add_argument(
        "--campaign",
        default="robustness/campaign.v1.json",
        type=Path,
        help="versioned robustness campaign JSON",
    )
    robust.add_argument(
        "--out",
        default="examples",
        type=Path,
        help="robustness report output directory",
    )
    robust.add_argument(
        "--live",
        action="store_true",
        help="use the optional live adapter",
    )
    robust.add_argument(
        "--model",
        default=None,
        help="model id for --live (default: CONTRACT_EVAL_MODEL, else claude-opus-5)",
    )
    robust.add_argument(
        "--runs",
        default=1,
        type=int,
        choices=range(1, 6),
        metavar="1..5",
        help="adapter runs per original and mutated contract",
    )
    vc = sub.add_parser(
        "verify-capture",
        help="verify a captured review's schema, integrity and embedded inputs",
    )
    vc.add_argument("--input", required=True, type=Path, help="captured review JSON")

    so = sub.add_parser(
        "score-output",
        help="re-score a captured review offline through the production scorer",
    )
    so.add_argument("--input", required=True, type=Path, help="captured review JSON")
    so.add_argument(
        "--aliases", default="on", choices=["on", "off", "both"],
        help="apply declared clause synonyms; 'both' scores the same bytes twice",
    )
    so.add_argument("--out", default=None, type=Path, help="directory for the replay result")
    so.add_argument(
        "--allow-input-drift", action="store_true",
        help="reproduce the historical result even though current inputs differ; "
             "the result is then comparison-only and ineligible for certification",
    )

    verify_robust = sub.add_parser(
        "verify-robustness",
        help="rebuild the offline campaign and verify its input-bound report",
    )
    verify_robust.add_argument(
        "--report",
        default="examples/adversarial-robustness-report.json",
        type=Path,
    )
    verify_robust.add_argument(
        "--campaign",
        default="robustness/campaign.v1.json",
        type=Path,
    )
    
    args = parser.parse_args()

    if args.cmd == "evaluate":
        try:
            path = evaluate(
                case=args.case,
                live=args.live,
                out_dir=args.out,
                no_gate=args.no_gate,
                format_type=args.format,
                model=args.model,
            )
            print(f"wrote {path}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    elif args.cmd == "compare":
        compare_runs()
    elif args.cmd == "certify":
        markdown_path, json_path = certify(case=args.case, out_dir=args.out)
        print(f"wrote {markdown_path} and {json_path}")
    elif args.cmd == "verify-certificate":
        verification = verify_certificate(args.certificate)
        print(json.dumps(verification, indent=2))
        if verification["status"] != "VALID":
            sys.exit(1)
    elif args.cmd == "robustness":
        try:
            report = robustness(
                args.campaign,
                args.out,
                live=args.live,
                runs=args.runs,
                model=args.model,
            )
        except (OSError, ValueError, KeyError) as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        print(
            f"wrote {args.out / 'adversarial-robustness-report.md'} "
            f"({report['suite_decision']})"
        )
    elif args.cmd == "verify-capture":
        from contract_eval.replay import load, verify_capture

        report = verify_capture(load(args.input))
        print(json.dumps(report, indent=2))
        if not report["authentic"]:
            sys.exit(1)
    elif args.cmd == "score-output":
        from contract_eval.replay import ReplayError, load, replay

        modes = ("on", "off") if args.aliases == "both" else (args.aliases,)
        try:
            result = replay(
                load(args.input),
                alias_modes=modes,
                allow_input_drift=args.allow_input_drift,
            )
        except ReplayError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            path = args.out / f"replay-{result['case']}.json"
            path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            print(f"wrote {path}")
        else:
            print(json.dumps(result, indent=2))
    elif args.cmd == "verify-robustness":
        verification = verify_robustness(args.report, args.campaign)
        print(json.dumps(verification, indent=2))
        if verification["status"] != "VALID":
            sys.exit(1)


if __name__ == "__main__":
    main()
