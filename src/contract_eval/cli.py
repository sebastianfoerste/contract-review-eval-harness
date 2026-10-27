"""The evaluate pipeline: source -> adapter -> scorer -> scorecard."""

import argparse
import datetime
import json
import sys
from pathlib import Path

from contract_eval import paths
from contract_eval.adapters import (
    AdapterChoice,
    adapter_choice,
    adapter_identifier,
    add_adapter_arguments,
    get_adapter,
)
# Re-exported: score_review and its helpers lived here before contract_eval.api, and
# callers import them from this module.
from contract_eval.api import (  # noqa: F401
    canonical_clause,
    canonicalise_risk_flags,
    regression_violations,
    score_review,
)
from contract_eval.cases import ALL_CASES
from contract_eval.models import ExpectedAnswer, ReviewOutput  # noqa: F401
from contract_eval.provenance import run_provenance, write_provenance
from contract_eval.scorecard import render
from contract_eval.release_certificate import (
    build_release_certificate,
    render_release_certificate,
    verify_release_certificate,
)
from contract_eval.robustness import (
    build_robustness_report,
    verify_robustness_report,
    write_robustness_report,
)


def load_case_inputs(case: str, root: Path | None = None) -> tuple[str, ExpectedAnswer]:
    root = paths.resolve_root(root)
    source = (root / paths.source_file(case)).read_text(encoding="utf-8")
    expected = ExpectedAnswer.model_validate(
        json.loads((root / paths.gold_file(case)).read_text(encoding="utf-8"))
    )
    return source, expected


def evaluate_case(
    case: str, live: bool, model: str | None = None, adapter: AdapterChoice | None = None
) -> dict:
    """Produce and score one review through the adapter."""
    source, expected = load_case_inputs(case)
    output = get_adapter(live, model=model, choice=adapter).review(source_text=source, case=case)
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


def evaluate(case: str, live: bool, out_dir: Path, no_gate: bool = False, format_type: str = "markdown", model: str | None = None, adapter: AdapterChoice | None = None) -> Path:
    cases_to_eval = ALL_CASES if case == "all" else [case]
    run_scores = {}

    for c in cases_to_eval:
        run_scores[c] = evaluate_case(c, live, model=model, adapter=adapter)

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
        adapter=adapter_identifier(live, model, choice=adapter),
        # The adapter produced this output during this call, so the two dates
        # coincide here. Re-scoring a stored output must set them apart.
        output_generated_at=datetime.datetime.now().isoformat(timespec="seconds"),
        scored_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    write_provenance(provenance, out_dir / "run-provenance.json")

    # History sits beside the scorecard, so a run with --out, and every test, writes
    # only into its own directory. --out defaults to the working directory, so a
    # plain run still records into ./history, where `compare` looks by default.
    history_dir = out_dir / "history"
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
        violations = [
            violation
            for c in cases_to_eval
            for violation in regression_violations(c, run_scores[c])
        ]

        if violations:
            print("\n=== demo-regression-policy.v2 GATE FAILED ===")
            for v in violations:
                print(f"- {v}")
            print("======================================")
            raise ValueError("Evaluation did not meet the required quality thresholds.")

    return path


def latest_run(history_dir: Path = Path("history")) -> Path:
    if not history_dir.exists():
        print("No history directory found. Run evaluate first to create history.")
        sys.exit(1)

    run_files = sorted(history_dir.glob("run_*.json"), key=lambda f: f.name)
    if not run_files:
        print("No previous run history files found. Run evaluate first.")
        sys.exit(1)
    return run_files[-1]


def compare_runs(
    history_dir: Path = Path("history"),
    *,
    baseline: Path | None = None,
    candidate: Path | None = None,
) -> bool:
    """Compare a candidate run with a baseline run and return whether it regressed.

    Without paths the baseline is the newest run in `history_dir` and the candidate is
    a fresh offline scoring of the current inputs. Straight after `evaluate` that
    newest run is the one just written, so the comparison measures a run against
    itself and cannot fail. CI therefore names a committed snapshot as the baseline
    and the fresh run as the candidate.
    """
    if baseline is None:
        baseline = latest_run(history_dir)
    if candidate is not None and baseline.resolve() == candidate.resolve():
        print(f"Baseline and candidate are the same file: {baseline}. Comparing a run with itself proves nothing.")
        sys.exit(1)

    past_scores = json.loads(baseline.read_text(encoding="utf-8"))["scores"]
    # The cases the baseline recorded, not today's ALL_CASES: an `all` snapshot taken
    # before a case was added has no scores for it.
    cases_to_eval = list(past_scores)

    if candidate is None:
        print(f"Comparing current scores against historical run: {baseline.name}")
        current_scores = {c: evaluate_case(c, live=False) for c in cases_to_eval}
    else:
        print(f"Comparing run {candidate.name} against historical run: {baseline.name}")
        current_scores = json.loads(candidate.read_text(encoding="utf-8"))["scores"]
        missing = [c for c in cases_to_eval if c not in current_scores]
        if missing:
            print(f"The candidate run has no scores for {', '.join(missing)}, which the baseline records.")
            sys.exit(1)
        not_compared = sorted(set(current_scores) - set(cases_to_eval))
        if not_compared:
            print(f"Not in the baseline, so not compared: {', '.join(not_compared)}")

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
        print(f"\nWarning: Performance regression detected relative to {baseline.name}.")
    else:
        print("\nSuccess: No regressions detected!")
    return regressed


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
    adapter: AdapterChoice | None = None,
) -> dict:
    scores = {
        case: evaluate_case(case, live=False)
        for case in ALL_CASES
    }
    certificate = build_release_certificate(scores)
    report = build_robustness_report(
        paths.resolve_input(campaign_path),
        get_adapter(live, model=model, choice=adapter),
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
        paths.resolve_input(campaign_path),
        get_adapter(False),
        build_release_certificate(scores),
    )
    return verify_robustness_report(report, expected)


class ScoreInputError(ValueError):
    """A review, contract or answer set given to `score` cannot be read or parsed."""


def _review_hint(review: Path) -> str:
    """Point a captured-review envelope at the command that verifies and replays it."""
    try:
        data = json.loads(review.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    from contract_eval.capture import CAPTURE_SCHEMA

    if isinstance(data, dict) and data.get("schema") == CAPTURE_SCHEMA:
        return (
            " It looks like a captured review; re-score it with "
            f"`contract-eval score-output --input {review}`."
        )
    return ""


def score(
    review: Path,
    *,
    case: str | None = None,
    contract: Path | None = None,
    gold: Path | None = None,
    alias_mode: str = "on",
) -> dict:
    """Score any tool's plain review JSON; no adapter, no capture envelope.

    A bundled case is scored against the reviewed answer set the release certificate
    uses. Your own contract and answer set go through the same `score_review`, and the
    result is comparison-only, the rule replay applies to drifted inputs: the harness
    cannot vouch for an answer set it has not reviewed.
    """
    from pydantic import ValidationError

    from contract_eval.api import evaluate_review, load_case

    try:
        target = load_case(case) if case is not None else load_case(contract=contract, gold=gold)
    except ValidationError as exc:
        raise ScoreInputError(
            f"{gold} is not a valid answer set (see schemas/expected-answer.schema.json):\n{exc}"
        ) from exc
    except (OSError, ValueError) as exc:
        raise ScoreInputError(str(exc)) from exc
    try:
        result = evaluate_review(review, target, alias_mode=alias_mode)
    except ValidationError as exc:
        raise ScoreInputError(
            f"{review} is not a plain review JSON (see schemas/review-output.schema.json)."
            f"{_review_hint(review)}\n{exc}"
        ) from exc
    except OSError as exc:
        raise ScoreInputError(str(exc)) from exc
    return result.to_dict()


def score_exit_code(decision: str, fail_on: str = "reject") -> int:
    """1 when the decision fails the gate: REJECT always, human review on request."""
    failing = {"REJECT"} if fail_on == "reject" else {"REJECT", "HUMAN_REVIEW_REQUIRED"}
    return 1 if decision in failing else 0


def _add_dev_commands(sub: argparse._SubParsersAction, *, listed: bool) -> None:
    """Maintainer commands: listed under `contract-eval dev`, and also accepted at the
    top level, unlisted, so existing scripts, Make targets and CI steps keep working."""

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        if listed:
            return sub.add_parser(name, help=help_text, description=help_text)
        return sub.add_parser(name, description=help_text)

    reference = add("reference-status", "verify the annotation evidence chain and report release eligibility")
    reference.add_argument("--require-final", action="store_true", help="fail until every reference is verified and frozen")
    reference.add_argument("--out", type=Path, help="write the verified status JSON")
    intake = add("reference-import", "import all original second-annotator returns without overwriting evidence")
    intake.add_argument("--returned", required=True, type=Path)
    prepare = add("reference-prepare", "write blank adjudication records bound to the imported comparison")
    prepare.add_argument("--out", required=True, type=Path)
    freeze = add("reference-freeze", "verify written decisions and atomically freeze all references")
    freeze.add_argument("--gold-dir", required=True, type=Path)
    freeze.add_argument("--decisions-dir", required=True, type=Path)

    verify = add("verify-certificate", "re-run the offline benchmark and verify a release certificate")
    verify.add_argument(
        "--certificate",
        default="examples/release-certificate.json",
        type=Path,
        help="release certificate JSON to verify",
    )
    obl = add("evaluate-obligations", "score a case through the evidence-bound v2 path")
    obl.add_argument("--case", default="nda", help="case name, or all")
    add_adapter_arguments(obl)
    obl.add_argument("--model", default=None, help="model id for --adapter anthropic or openai-compatible")
    obl.add_argument("--out", default=None, type=Path, help="output directory")

    vc = add("verify-capture", "verify a captured review's schema, integrity and embedded inputs")
    vc.add_argument("--input", required=True, type=Path, help="captured review JSON")

    verify_robust = add("verify-robustness", "rebuild the offline campaign and verify its input-bound report")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contract-eval",
        description="Score an AI contract review against a hand-authored answer set.",
        epilog="maintainer commands: contract-eval dev --help",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    ev = sub.add_parser("evaluate", help="score an adapter's review against the expected answers")
    ev.add_argument("--case", default="nda", help="case name (nda, saas, all)")
    add_adapter_arguments(ev)
    ev.add_argument(
        "--model",
        default=None,
        help="model id for --adapter anthropic (default: CONTRACT_EVAL_MODEL, else claude-opus-5) "
             "or openai-compatible (required)",
    )
    ev.add_argument("--out", default=".", type=Path, help="output directory for scorecard.md, run-provenance.json and history/")
    ev.add_argument("--no-gate", action="store_true", help="do not exit with code 1 on regression/failure")
    ev.add_argument("--format", default="markdown", choices=["markdown", "json"], help="output format (markdown, json)")

    cmp = sub.add_parser(
        "compare",
        help="compare a run against a saved baseline run; exit with code 1 on a regression",
    )
    cmp.add_argument(
        "--baseline",
        default=None,
        type=Path,
        help="run JSON to compare against (default: the newest history/run_*.json)",
    )
    cmp.add_argument(
        "--candidate",
        default=None,
        type=Path,
        help="run JSON to compare (default: score the current inputs offline)",
    )
    cert = sub.add_parser(
        "certify",
        help="issue an input-bound release decision over the synthetic benchmark suite",
    )
    cert.add_argument("--case", default="all", help="case name (nda, saas, all)")
    cert.add_argument("--out", default="examples", type=Path, help="certificate output directory")
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
    add_adapter_arguments(robust)
    robust.add_argument(
        "--model",
        default=None,
        help="model id for --adapter anthropic (default: CONTRACT_EVAL_MODEL, else claude-opus-5) "
             "or openai-compatible (required)",
    )
    robust.add_argument(
        "--runs",
        default=1,
        type=int,
        choices=range(1, 6),
        metavar="1..5",
        help="adapter runs per original and mutated contract",
    )

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

    sc = sub.add_parser(
        "score",
        help="score your own tool's review JSON against a bundled or your own answer set",
        description=(
            "Score a plain review JSON (schemas/review-output.schema.json) and print the "
            "scorecard. Exit status: 0 passed, 1 REJECT (or human review with "
            "--fail-on human-review), 2 unreadable input."
        ),
    )
    sc.add_argument("review", type=Path, help="review JSON produced by the tool under test")
    sc.add_argument("--case", default=None, help=f"bundled case: {', '.join(ALL_CASES)}")
    sc.add_argument("--contract", default=None, type=Path, help="your contract, instead of --case")
    sc.add_argument(
        "--gold", default=None, type=Path,
        help="your answer set for --contract (schemas/expected-answer.schema.json)",
    )
    sc.add_argument(
        "--aliases", default="on", choices=["on", "off"],
        help="apply the answer set's declared clause synonyms (default: on)",
    )
    sc.add_argument("--format", default="markdown", choices=["markdown", "json"], help="what to print")
    sc.add_argument("--out", default=None, type=Path, help="also write score-<case>.md and .json here")
    sc.add_argument(
        "--fail-on", default="reject", choices=["reject", "human-review"],
        help="lowest decision that exits 1 (default: reject)",
    )

    dev = sub.add_parser(
        "dev",
        help="maintainer commands: verification, reference evidence, obligations",
        description="Maintainer commands. Each is also accepted without the `dev` prefix.",
    )
    _add_dev_commands(dev.add_subparsers(dest="dev_cmd", required=True, metavar="<command>"), listed=True)
    _add_dev_commands(sub, listed=False)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "dev":
        args.cmd = args.dev_cmd

    if args.cmd == "evaluate":
        try:
            path = evaluate(
                case=args.case,
                live=args.live,
                out_dir=args.out,
                no_gate=args.no_gate,
                format_type=args.format,
                model=args.model,
                adapter=adapter_choice(args),
            )
            print(f"wrote {path}")
        except (ValueError, RuntimeError) as e:  # RuntimeError: adapter failures
            print(f"Error: {e}")
            sys.exit(1)
    elif args.cmd == "compare":
        try:
            regressed = compare_runs(baseline=args.baseline, candidate=args.candidate)
        except (OSError, ValueError, KeyError) as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        if regressed:
            sys.exit(1)
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
                adapter=adapter_choice(args),
            )
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        print(
            f"wrote {args.out / 'adversarial-robustness-report.md'} "
            f"({report['suite_decision']})"
        )
    elif args.cmd in ("reference-status", "reference-import", "reference-prepare", "reference-freeze"):
        from contract_eval.reference_evidence import (
            reference_status, import_returns, adjudication_templates, freeze_references, encoded,
        )
        try:
            if args.cmd == "reference-import":
                import_returns(Path.cwd(), args.returned)
            elif args.cmd == "reference-prepare":
                adjudication_templates(Path.cwd(), args.out)
            elif args.cmd == "reference-freeze":
                freeze_references(Path.cwd(), args.gold_dir, args.decisions_dir)
            result = reference_status(Path.cwd())
            if args.cmd == "reference-status" and args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_bytes(encoded(result))
            print(encoded(result).decode("utf-8"), end="")
            if result["stage"] == "invalid" or (args.cmd == "reference-status" and args.require_final and not result["finalReleaseEligible"]):
                sys.exit(1)
        except (OSError, ValueError) as exc:
            print(f"Reference evidence error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.cmd == "evaluate-obligations":
        from contract_eval.obligation_cli import evaluate_obligations, render

        cases = ALL_CASES if args.case == "all" else [args.case]
        for case in cases:
            result = evaluate_obligations(
                case, live=args.live, model=args.model, adapter=adapter_choice(args)
            )
            if args.out:
                args.out.mkdir(parents=True, exist_ok=True)
                (args.out / f"obligation-scorecard-{case}.json").write_text(
                    json.dumps(result, indent=2, ensure_ascii=False) + "\n"
                )
                (args.out / f"obligation-scorecard-{case}.md").write_text(render(result))
                print(f"wrote {args.out / f'obligation-scorecard-{case}.md'}")
            else:
                print(render(result))
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
    elif args.cmd == "score":
        from contract_eval.scorecard import render_score

        own = args.contract is not None or args.gold is not None
        if args.case is not None and own:
            parser.error("score: pass --case for a bundled case, or --contract and --gold, not both")
        if args.case is None and (args.contract is None or args.gold is None):
            parser.error("score: pass --case <name>, or both --contract and --gold")
        try:
            result = score(
                args.review,
                case=args.case,
                contract=args.contract,
                gold=args.gold,
                alias_mode=args.aliases,
            )
        except ScoreInputError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        markdown = render_score(result)
        encoded_result = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            for suffix, text in (("md", markdown), ("json", encoded_result)):
                path = args.out / f"score-{result['case']}.{suffix}"
                path.write_text(text, encoding="utf-8")
                print(f"wrote {path}", file=sys.stderr)
        print(markdown if args.format == "markdown" else encoded_result, end="")
        code = score_exit_code(result["decision"], args.fail_on)
        if code:
            sys.exit(code)


if __name__ == "__main__":
    main()
