"""The matter path: a round of a matter, scored under each condition side by side.

    matter + round
          |
          +-- condition A: documents A may see -> adapter -> review -> score
          +-- condition B: documents B may see -> adapter -> review -> score
          |
          v
    one scorecard, one column per condition, against the same answers

The comparison between columns is the experiment. Everything else in this module is
there to stop the scorecard saying more than was measured: it prints the status of
the answers, whether the output came from a fixture or a model, and whether the
evaluation split had already been looked at.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from contract_eval.adapters.matter import (
    MATTER_ADAPTERS,
    STUB_MODEL,
    MatterFixtureMissing,
    get_matter_adapter,
    load_review_file,
    parse_review_file,
    render_prompt,
)
from contract_eval.matter import (
    MATTERS_DIR,
    LoadedMatter,
    MatterIssue,
    MatterReview,
    file_sha256,
    load_matter,
)
from contract_eval.matter_experiment import (
    append_entry,
    configuration_id,
    default_log_path,
    eval_guard,
    read_log,
    text_digest,
)
from contract_eval.matter_scorer import find_whole, score_matter
from contract_eval.scorer import build_normalized_index, normalize_text
from contract_eval.reviewer_sessions import (
    blank_session,
    load_sessions,
    summarise_sessions,
    validate_against_review,
)

SCORECARD_SCHEMA = "contract-review-eval.matter-scorecard.v1"
DEFAULT_MATTER = "northwind-saas"


def list_matters(root: Path = Path(".")) -> list[str]:
    directory = root / MATTERS_DIR
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if (p / "matter.json").is_file())


def _claim_scope(gold_status: dict[str, Any], authored: bool, sources: set[str]) -> list[str]:
    scope = []
    if not authored:
        scope.append(
            "Nothing is scored. The answers for this round have not been written, and "
            "the harness does not generate them."
        )
        return scope
    if sources == {STUB_MODEL}:
        scope.append(
            "Outputs are committed fixtures, not model output. Differences between "
            "conditions were constructed and demonstrate the instrument only."
        )
    elif len(sources) > 1:
        scope.append(
            "The conditions were not produced the same way (" + ", ".join(sorted(sources))
            + "). Differences between them are not a measurement of the conditions."
        )
    if not (
        gold_status["annotation_status"] == "frozen"
        and gold_status["adjudication_status"] == "complete"
    ):
        scope.append(
            f"The answers are {gold_status['annotation_status']} with adjudication "
            f"{gold_status['adjudication_status']}. They carry one annotator's judgment "
            "and are not a validated benchmark."
        )
    return scope


def evaluate_matter(
    matter_id: str,
    round_id: str,
    *,
    conditions: list[str] | None = None,
    split: str | None = None,
    live: bool = False,
    model: str | None = None,
    root: Path = Path("."),
    reviews: dict[str, Path] | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Score one round under each requested condition.

    `reviews` maps a condition to an output file to score instead of calling the
    adapter. That is how a run captured before the answers existed gets scored once
    they do, without paying for or re-rolling the model call.
    """
    loaded = load_matter(matter_id, root)
    gold = loaded.gold(round_id)
    reviews = reviews or {}
    condition_ids = conditions or [c.condition_id for c in loaded.matter.conditions]
    for condition_id in condition_ids:
        loaded.matter.condition(condition_id)  # fail on an unknown id before any call
    stray = sorted(set(reviews) - set(condition_ids))
    if stray:
        # A mistyped condition would otherwise fall through to the adapter, and with
        # --live that is a model call nobody asked for.
        raise ValueError(
            f"review files given for conditions that are not being scored: {stray}"
        )
    needs_adapter = any(c not in reviews for c in condition_ids)
    adapter = get_matter_adapter(live, model=model) if needs_adapter else None

    # Anything other than the committed fixtures is a real result and is logged, or
    # scoring captures after the answers are written would bypass the guard entirely.
    if log_path is None and gold.authored and (live or reviews):
        log_path = default_log_path(matter_id, root)
    log = read_log(log_path) if log_path else []
    sessions = [
        s for s in load_sessions(loaded.directory / "reviews")
        if s.matter_id == matter_id and s.round_id == round_id
    ]

    order = [r.round_id for r in loaded.matter.rounds]
    earlier: list[MatterIssue] = []
    for previous in order[: order.index(round_id)]:
        earlier += loaded.gold(previous).issues
    gold_sha256 = file_sha256(loaded.directory / loaded.matter.round(round_id).expected)

    gold_status = gold.status.model_dump()
    result: dict[str, Any] = {
        "schema": SCORECARD_SCHEMA,
        "matter_id": matter_id,
        "round_id": round_id,
        "split": split or "all",
        "gold_status": gold_status,
        "gold_sha256": gold_sha256,
        "conditions": [],
    }

    for condition_id in condition_ids:
        visible = loaded.visible_texts(round_id, condition_id)
        entry: dict[str, Any] = {
            "condition_id": condition_id,
            "visible_documents": list(visible),
            "scores": None,
        }
        result["conditions"].append(entry)

        prompt_sha256 = text_digest(render_prompt(loaded, round_id, condition_id))
        if condition_id in reviews:
            review, meta = load_review_file(reviews[condition_id])
            claimed = {k: meta[k] for k in ("matter_id", "round_id", "condition_id") if k in meta}
            actual = {"matter_id": matter_id, "round_id": round_id, "condition_id": condition_id}
            if any(actual[k] != v for k, v in claimed.items()):
                raise ValueError(
                    f"{reviews[condition_id]} was captured for {claimed}, and is being "
                    f"scored as {actual}"
                )
            # A capture knows the prompt and model that produced it. A bare file
            # knows nothing, so its content is its only identity.
            source = meta.get("model") or "review-file"
            configuration = configuration_id(
                **actual,
                prompt_sha256=meta.get("prompt_sha256"),
                model=meta.get("model"),
                effort=meta.get("effort"),
                output_sha256=None if meta else review.canonical_sha256(),
            )
        else:
            try:
                review = adapter.review(loaded, round_id, condition_id)
            except MatterFixtureMissing as exc:
                entry["unavailable"] = str(exc)
                continue
            source = adapter.model
            configuration = configuration_id(
                matter_id=matter_id, round_id=round_id, condition_id=condition_id,
                prompt_sha256=prompt_sha256, model=adapter.model, effort=adapter.effort,
            )

        entry["source"] = source
        entry["review_sha256"] = review.canonical_sha256()
        if not gold.authored:
            entry["unavailable"] = "answers not written; output obtained but not scored"
            continue

        entry["configuration_id"] = configuration
        scores = score_matter(visible, gold, review, split=split, earlier_issues=earlier)
        entry["scores"] = asdict(scores)

        matching = [s for s in sessions if s.review_sha256 == entry["review_sha256"]]
        for session in matching:
            validate_against_review(session, review)
        reviewers = [s.reviewer_id for s in matching]
        repeated = sorted({r for r in reviewers if reviewers.count(r) > 1})
        if repeated:
            raise ValueError(
                f"reviewers {repeated} have more than one session for the same output "
                f"of condition {condition_id!r}"
            )
        entry["reviewer_usefulness"] = summarise_sessions(matching)

        if log_path:
            if result["split"] in ("eval", "all"):
                entry["eval_guard"] = eval_guard(
                    log, matter_id=matter_id, round_id=round_id,
                    condition_id=condition_id, configuration=configuration,
                    gold_sha256=gold_sha256,
                )
            append_entry(log_path, {
                "matter_id": matter_id,
                "round_id": round_id,
                "condition_id": condition_id,
                "split": result["split"],
                "configuration_id": configuration,
                "gold_sha256": gold_sha256,
                "source": source,
                "review_sha256": entry["review_sha256"],
                "issue_recall": scores.issue_recall,
                "material_recall": scores.material_recall,
                "finding_precision": scores.finding_precision,
                "citation_grounding": scores.citation_grounding,
            })

    sources = {c["source"] for c in result["conditions"] if "source" in c}
    result["adapter"] = ", ".join(sorted(sources)) or (adapter.model if adapter else "none")
    result["claim_scope"] = _claim_scope(gold_status, gold.authored, sources)
    return result


# ---------------------------------------------------------------------------- render


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


_ROWS: tuple[tuple[str, Any], ...] = (
    ("Issue recall", lambda s: _number(s["issue_recall"])),
    ("Material-issue recall", lambda s: _number(s["material_recall"])),
    ("Conflict recall", lambda s: _number(s["task_recall"]["conflict"])),
    ("Position recall", lambda s: _number(s["task_recall"]["position"])),
    ("Escalation recall", lambda s: _number(s["task_recall"]["escalation"])),
    ("Finding precision", lambda s: _number(s["finding_precision"])),
    ("Escalation precision", lambda s: _number(s["escalation_precision"])),
    ("Action accuracy", lambda s: _number(s["action_accuracy"])),
    ("Materiality accuracy", lambda s: _number(s["materiality_accuracy"])),
    ("False reassurance", lambda s: str(len(s["false_reassurance"]))),
    ("Citation grounding", lambda s: _number(s["citation_grounding"])),
    ("Misattributed citations", lambda s: str(s["citations"]["misattributed"])),
    ("Unsupported citations", lambda s: str(s["citations"]["unsupported"])),
    ("Citations to documents not shown", lambda s: str(s["citations"]["not_visible"])),
    ("Citations no finding relies on", lambda s: str(s["unreferenced_citations"])),
)


def _usefulness(entry: dict[str, Any]) -> str:
    summary = entry.get("reviewer_usefulness") or {}
    if not summary.get("measured"):
        return "not measured"
    return f"{summary['mean_usefulness']:.2f} (n={summary['reviewers']})"


def render_matter(result: dict[str, Any]) -> str:
    status = result["gold_status"]
    lines = [
        f"# Matter scorecard: {result['matter_id']}, {result['round_id']}",
        "",
        f"Split: {result['split']}. Adapter: {result['adapter']}.",
        "Answers: pending." if status["annotation_status"] == "pending" else
        f"Answers: {status['annotation_status']} by {status['annotator_id']}, "
        f"adjudication {status['adjudication_status']}.",
        "",
    ]
    lines += [f"> {line}" for line in result["claim_scope"]]
    if result["claim_scope"]:
        lines.append("")

    scored = [c for c in result["conditions"] if c["scores"]]
    if scored:
        header = " | ".join(c["condition_id"] for c in scored)
        lines += [
            f"| Measure | {header} |",
            "|---|" + "---:|" * len(scored),
            "| Documents shown | "
            + " | ".join(str(len(c["visible_documents"])) for c in scored) + " |",
            "| Issues answerable from those documents | "
            + " | ".join(
                f"{c['scores']['issues_answerable']}/{c['scores']['issues_total']}"
                for c in scored
            ) + " |",
        ]
        for label, cell in _ROWS:
            lines.append(
                f"| {label} | " + " | ".join(cell(c["scores"]) for c in scored) + " |"
            )
        lines += [
            "| Reviewer usefulness (1 to 4) | "
            + " | ".join(_usefulness(c) for c in scored) + " |",
            "",
        ]

    for entry in result["conditions"]:
        lines += [f"## Condition: {entry['condition_id']}", ""]
        lines.append("Documents shown: " + ", ".join(f"`{d}`" for d in entry["visible_documents"]))
        lines.append("")
        if not entry["scores"]:
            lines += [f"Not scored: {entry.get('unavailable', 'unknown reason')}.", ""]
            continue
        scores = entry["scores"]
        for title, key in (
            ("Material issues missed", "missed_material"),
            ("False reassurance: told to accept a material term", "false_reassurance"),
            ("Contradictory actions on one issue", "conflicting_actions"),
            ("Findings matching no expected issue", "unexpected_findings"),
            ("Findings restating an earlier round, not scored", "restated_findings"),
            ("Issues found more than once", "duplicate_issue_findings"),
        ):
            if scores[key]:
                lines.append(f"{title}: " + ", ".join(f"`{i}`" for i in scores[key]))
        for finding_id, reason in scores["unbound_findings"].items():
            lines.append(f"Finding `{finding_id}` earned nothing: {reason}")
        guard = entry.get("eval_guard")
        if guard and guard["contaminated"]:
            lines += ["", f"**Not held out.** {guard['note']}"]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------------------- check


def check_matter(matter_id: str, root: Path = Path(".")) -> dict[str, list[str]]:
    """Structural checks only. Whether an answer is legally right is not checkable here."""
    errors: list[str] = []
    notices: list[str] = []
    try:
        loaded = load_matter(matter_id, root)
    except (OSError, ValueError) as exc:
        return {"errors": [str(exc)], "notices": []}

    for condition in loaded.matter.conditions:
        for round_ in loaded.matter.rounds:
            try:
                render_prompt(loaded, round_.round_id, condition.condition_id)
            except (OSError, ValueError) as exc:
                errors.append(f"{condition.condition_id}: {exc}")
                break

    golds = {}
    for round_ in loaded.matter.rounds:
        try:
            gold = golds[round_.round_id] = loaded.gold(round_.round_id)
        except (OSError, ValueError) as exc:
            errors.append(f"{round_.round_id}: {exc}")
            continue
        if not gold.authored:
            notices.append(f"{round_.round_id}: answers pending, nothing can be scored")
            continue
        _check_gold(loaded, round_.round_id, gold, errors, notices)

    fixtures = loaded.directory / "fixtures"
    for path in sorted(fixtures.glob("*.json")) if fixtures.is_dir() else []:
        round_id, _, condition_id = path.stem.partition(".")
        try:
            loaded.matter.round(round_id)
            loaded.matter.condition(condition_id)
            parse_review_file(path)
        except (OSError, ValueError) as exc:
            errors.append(f"fixtures/{path.name}: {exc}")

    try:
        load_sessions(loaded.directory / "reviews")
    except (OSError, ValueError) as exc:
        errors.append(f"reviews: {exc}")

    return {"errors": errors, "notices": notices}


def _check_gold(loaded: LoadedMatter, round_id: str, gold, errors, notices) -> None:
    playbooks = " ".join(
        loaded.texts[d.document_id]
        for d in loaded.matter.documents_in_round(round_id) if d.kind == "playbook"
    )
    # A review's quote is matched after normalising case, punctuation and spacing. An
    # answer passage that is unique as raw text can still occur twice once normalised,
    # and a verbatim citation of it would then be ambiguous and never credited.
    indexes = {
        doc_id: build_normalized_index(text)
        for doc_id, text in loaded.texts_in_round(round_id).items()
    }
    for issue in gold.issues:
        for span in issue.evidence:
            found = find_whole(indexes[span.document_id], normalize_text(span.quote))
            if len(found) != 1:
                errors.append(
                    f"{issue.issue_id}: the passage in {span.document_id} occurs "
                    f"{len(found)} times as whole words after normalisation, so a "
                    f"citation of it could not be located: {span.quote!r}"
                )
    for issue in gold.issues:
        rule = issue.playbook_rule
        if rule and not re.search(rf"(?<![\w-]){re.escape(rule)}(?![\w-])", playbooks):
            errors.append(
                f"{issue.issue_id}: playbook rule {rule!r} is not in any playbook "
                f"document of round {round_id}"
            )
    splits = {issue.split for issue in gold.issues}
    for split in ("dev", "eval"):
        if split not in splits:
            notices.append(f"{round_id}: no issue is assigned to the {split} split")


# ------------------------------------------------------------------------------- cli


def add_parsers(add: Callable[[str, str], argparse.ArgumentParser]) -> None:
    """Register the matter commands through `add(name, help)`.

    cli.py passes the factory it uses for the maintainer commands, so these are listed
    under `contract-eval dev` and accepted, unlisted, at the top level.
    """

    def common(parser: argparse.ArgumentParser, with_round: bool = True) -> None:
        parser.add_argument("--matter", default=DEFAULT_MATTER, help="matter id")
        parser.add_argument("--root", default=Path("."), type=Path, help="repository root")
        if with_round:
            parser.add_argument("--round", default=None, help="round id; default is the first")

    evaluate = add("matter-evaluate", "score one round of a matter under each condition")
    common(evaluate)
    evaluate.add_argument(
        "--condition", action="append", default=None,
        help="condition id; repeat for several, default is all",
    )
    evaluate.add_argument("--split", default="all", choices=["dev", "eval", "all"])
    # The adapter flags of the case commands, cut down to the adapters a matter has, so
    # --live means --adapter anthropic here too.
    adapter = evaluate.add_mutually_exclusive_group()
    adapter.add_argument(
        "--adapter", default=None, choices=MATTER_ADAPTERS,
        help="which adapter produces the review (default: stub)",
    )
    adapter.add_argument("--live", action="store_true", help="alias for --adapter anthropic")
    evaluate.add_argument(
        "--model", default=None,
        help="model id for --adapter anthropic (default: CONTRACT_EVAL_MODEL, else claude-opus-5)",
    )
    evaluate.add_argument(
        "--review", action="append", default=[], metavar="CONDITION=PATH",
        help="score this output file for a condition instead of calling the adapter",
    )
    evaluate.add_argument(
        "--log", default=None, type=Path,
        help="experiment log to read and append to; a live run, or one scored with "
             "--review, uses experiments/<matter>/log.jsonl",
    )
    evaluate.add_argument("--out", default=None, type=Path, help="output directory")

    check = add("matter-check", "verify a matter's documents, answers and fixtures")
    check.add_argument("--matter", default="all", help="matter id, or all")
    check.add_argument("--root", default=Path("."), type=Path, help="repository root")

    prompt = add("matter-prompt", "print the prompt a condition produces")
    common(prompt)
    prompt.add_argument("--condition", required=True)

    template = add(
        "matter-review-template",
        "write a blank reviewer session for one output, with the condition withheld",
    )
    common(template)
    template.add_argument("--condition", default=None, help="condition whose stub output to rate")
    template.add_argument("--review", default=None, type=Path, help="output file to rate")
    template.add_argument("--out", required=True, type=Path)


def _first_round(matter_id: str, root: Path, round_id: str | None) -> str:
    return round_id or load_matter(matter_id, root).matter.rounds[0].round_id


def run(args: argparse.Namespace) -> int:
    try:
        if args.cmd == "matter-check":
            matters = list_matters(args.root) if args.matter == "all" else [args.matter]
            failed = False
            for matter_id in matters:
                report = check_matter(matter_id, args.root)
                for notice in report["notices"]:
                    print(f"{matter_id}: notice: {notice}")
                for error in report["errors"]:
                    print(f"{matter_id}: ERROR: {error}")
                failed = failed or bool(report["errors"])
            print("matter check failed" if failed else f"matter check passed ({len(matters)} matters)")
            return 1 if failed else 0

        round_id = _first_round(args.matter, args.root, args.round)

        if args.cmd == "matter-prompt":
            loaded = load_matter(args.matter, args.root)
            print(render_prompt(loaded, round_id, args.condition))
            return 0

        if args.cmd == "matter-review-template":
            loaded = load_matter(args.matter, args.root)
            if args.review:
                review: MatterReview = parse_review_file(args.review)
            elif args.condition:
                review = get_matter_adapter(False).review(loaded, round_id, args.condition)
            else:
                raise ValueError("give --review or --condition")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(blank_session(args.matter, round_id, review), indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"wrote {args.out}")
            return 0

        reviews: dict[str, Path] = {}
        for item in args.review:
            condition_id, separator, path = item.partition("=")
            if not separator:
                raise ValueError(f"--review expects CONDITION=PATH, got {item!r}")
            reviews[condition_id] = Path(path)
        result = evaluate_matter(
            args.matter, round_id,
            conditions=args.condition,
            split=None if args.split == "all" else args.split,
            live=args.live or args.adapter == "anthropic", model=args.model, root=args.root,
            reviews=reviews, log_path=args.log,
        )
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            stem = f"matter-scorecard-{args.matter}-{round_id}-{result['split']}"
            (args.out / f"{stem}.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (args.out / f"{stem}.md").write_text(render_matter(result), encoding="utf-8")
            print(f"wrote {args.out / f'{stem}.md'}")
        else:
            print(render_matter(result), end="")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}")
        return 1
