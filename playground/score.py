"""Browser bridge for the playground. It scores through the CLI's own `score` path.

The review is written to a file and handed to `contract_eval.cli.score`, so the JSON
the page exports is the result `contract-eval score <file> --case <case>` writes for
the same bytes, down to its `result_sha256`. The findings list is a reading aid
derived from that result and the same scorer functions; it never feeds the decision.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from contract_eval.api import canonical_clause, load_case
from contract_eval.cli import ScoreInputError, score
from contract_eval.models import ReviewOutput
from contract_eval.release_certificate import REQUIREMENTS
from contract_eval.scorecard import _decision_note, render_score
from contract_eval.scorer import build_normalized_index, grounded_span, normalize_text

WORKDIR = Path("/tmp/contract-eval-playground")
DEFAULT_NAME = "review.json"
REQUIREMENT_TEXT = {r.failure_code: r.description for r in REQUIREMENTS}


def _file_name(name: str) -> str:
    # The result records the review's path, so keep the imported name without its directory.
    stem = re.sub(r"[^\w .-]", "_", Path(name.replace("\\", "/")).stem).strip(" .")
    return f"{stem}.json" if stem else DEFAULT_NAME


def raw_span(source_text: str, quote: str) -> list[int] | None:
    """Where a grounded quote sits in the contract as written, for highlighting."""
    norm_quote = normalize_text(quote)
    if not norm_quote:
        return None
    spans = build_normalized_index(source_text).find_all(norm_quote)
    return list(spans[0]) if spans else None


def _finding(category: str, status: str, label: str, detail: list[str], meta: str, key: str, span=None) -> dict:
    return {"category": category, "status": status, "label": label, "detail": detail, "meta": meta, "key": key, "span": span}


def findings(review: ReviewOutput, case, result: dict) -> list[dict]:
    """One row per citation, clause and risk, labelled with the policy's failure code."""
    source = case.source_text
    expected = case.expected
    aliases = expected.clause_aliases if result["alias_mode"] == "on" else {}
    scores = result["scores"]
    rows: list[dict] = []

    for index, citation in enumerate(review.citations, 1):
        meta = f"Citation {index} · {citation.clause_type}"
        if grounded_span(source, citation.quote) is None:
            rows.append(_finding(
                "citation", "blocker", f"“{citation.quote}”",
                ["Not an exact span of the contract after normalising case, punctuation and whitespace.",
                 "It counts as a hallucination. Any ungrounded citation rejects the review."],
                meta, "unsupported_citation_detected",
            ))
        else:
            rows.append(_finding(
                "citation", "pass", f"“{citation.quote}”",
                ["Found as an exact span of the normalised contract."],
                meta, "citation_grounded", raw_span(source, citation.quote),
            ))
    if not review.citations:
        rows.append(_finding(
            "citation", "blocker", "The review cites nothing",
            ["Grounding over zero citations is 0.00, so no finding of the review is tied to the contract."],
            "Citations", "citation_grounding_below_100_percent",
        ))

    predicted = {canonical_clause(c.clause_type, aliases) for c in review.clauses}
    for clause_type in expected.clause_types:
        anchor = expected.clause_anchors.get(clause_type)
        span = raw_span(source, anchor) if anchor else None
        if clause_type in predicted:
            rows.append(_finding("clause", "pass", clause_type, ["The review reports this clause."], "Clause", "clause_found", span))
        else:
            rows.append(_finding(
                "clause", "review", clause_type, ["The answer set declares this clause and the review does not report it."],
                "Clause", "expected_clause_missed", span,
            ))
    for clause_type in sorted(predicted - set(expected.clause_types)):
        rows.append(_finding(
            "clause", "review", clause_type,
            ["The review reports a clause the answer set does not declare. Declared aliases are applied first."
             if aliases else "The review reports a clause the answer set does not declare. Aliases are off."],
            "Clause", "unexpected_clause_extracted",
        ))

    flagged: dict[str, str] = {}
    for flag in review.risk_flags:
        flagged.setdefault(canonical_clause(flag.clause_type, aliases), flag.severity)
    rationale = expected.severity_rationale
    for clause_type, gold in expected.risk_flags.items():
        anchor = expected.clause_anchors.get(clause_type)
        span = raw_span(source, anchor) if anchor else None
        why = [f"Answer-set rationale: {rationale[clause_type]}"] if clause_type in rationale else []
        got = flagged.get(clause_type)
        if got is None:
            rows.append(_finding("risk", "review", clause_type, [f"The answer set flags this clause {gold}; the review does not flag it.", *why],
                                 f"Risk · gold {gold}", "expected_risk_missed", span))
        elif got != gold:
            rows.append(_finding("risk", "review", clause_type, [f"The review rates it {got}; the answer set rates it {gold}.", *why],
                                 f"Risk · gold {gold} · review {got}", "risk_severity_mismatch", span))
        else:
            rows.append(_finding("risk", "pass", clause_type, [f"Flagged at the answer set's severity, {gold}.", *why],
                                 f"Risk · {gold}", "risk_flagged", span))
    for clause_type in scores["risk_false_positives"]:
        rows.append(_finding(
            "risk", "review", clause_type,
            [f"The review flags it {flagged[clause_type]}; the answer set does not treat this clause as a risk."],
            f"Risk · review {flagged[clause_type]}", "risk_false_positive",
        ))
    for clause_type in scores["risk_duplicate_flags"]:
        conflicting = clause_type in scores["risk_conflicting_flags"]
        rows.append(_finding(
            "risk", "review", clause_type,
            ["Two or more flags collapse onto this clause" + (" with different severities." if conflicting else "."),
             "The first flag is the one scored."],
            "Risk", "conflicting_risk_flags" if conflicting else "duplicate_risk_flags",
        ))

    for clause_type in scores["span_uncovered_clauses"]:
        anchor = expected.clause_anchors.get(clause_type)
        rows.append(_finding(
            "coverage", "note", clause_type,
            ["No grounded citation lands inside this clause. Span coverage is a diagnostic; it does not change the decision."],
            "Span coverage", "span_uncovered", raw_span(source, anchor) if anchor else None,
        ))
    return rows


def score_text(review_text: str, case: str, alias_mode: str = "on", name: str = "") -> str:
    """Score a review JSON string; returns JSON with the result, scorecard and findings."""
    file_name = _file_name(name)
    previous = os.getcwd()
    path = WORKDIR / file_name
    try:
        WORKDIR.mkdir(parents=True, exist_ok=True)
        path.write_text(review_text, encoding="utf-8")
        # Relative, so the exported result records the file name the way a CLI run in its folder would.
        os.chdir(WORKDIR)
        result = score(Path(file_name), case=case, alias_mode=alias_mode)
        loaded = load_case(case)
        review = ReviewOutput.model_validate_json(review_text)
        return json.dumps({
            "result": result,
            # The bytes `contract-eval score --out` writes; JavaScript would print 1.0 as 1.
            "result_json": json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            "markdown": render_score(result),
            "note": _decision_note(result),
            "findings": findings(review, loaded, result),
            "requirements": REQUIREMENT_TEXT,
        })
    except ScoreInputError as exc:
        # Written for the user; tracebacks never leave the worker.
        return json.dumps({"error": str(exc)})
    finally:
        os.chdir(previous)
        path.unlink(missing_ok=True)

