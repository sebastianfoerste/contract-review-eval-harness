"""Findings are scored on the text they cite, not on what they are called."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval.evidence import (
    UNBOUND_AMBIGUOUS,
    UNBOUND_NO_EVIDENCE,
    UNBOUND_SPLIT,
    UNBOUND_UNRESOLVED,
    bind_review,
)
from contract_eval.gold_v2 import ExpectedAnswerV2
from contract_eval.obligation_scorer import assign_citation, score_obligations
from contract_eval.review_v2 import ReviewOutputV2
from contract_eval.scorer import build_normalized_index


def _case(case="dpa"):
    source = Path(f"data/{case}_sample.md").read_text()
    gold = ExpectedAnswerV2.model_validate(
        json.loads(Path(f"annotations/drafts/{case}.candidate.v2.json").read_text())
    )
    return source, gold


def _review(**parts):
    base = {"schema": "contract-review-eval.review-output.v2",
            "citations": [], "clauses": [], "risk_flags": [], "abstentions": []}
    base.update(parts)
    return ReviewOutputV2.model_validate(base)


def test_clause_labels_cannot_earn_or_lose_credit():
    """The core claim: rename every finding, score identically."""
    source, gold = _case()
    citations = [{"citation_id": "c1", "quote": "engage sub-processors at its own discretion"}]

    gold_name = _review(
        citations=citations,
        clauses=[{"finding_id": "f1", "clause_type": "subprocessor_authorization",
                  "text": "x", "evidence": ["c1"]}],
    )
    other_name = _review(
        citations=citations,
        clauses=[{"finding_id": "f1", "clause_type": "totally_different_label",
                  "text": "x", "evidence": ["c1"]}],
    )

    a = bind_review(source, gold, gold_name)
    b = bind_review(source, gold, other_name)

    assert a.clause_bindings[0].obligation_id == "dpa.subprocessor_authorization"
    assert b.clause_bindings[0].obligation_id == a.clause_bindings[0].obligation_id
    assert a.obligation_recall == b.obligation_recall


def test_a_finding_without_evidence_is_unbound():
    source, gold = _case()
    review = _review(clauses=[{"finding_id": "f1", "clause_type": "audit_rights",
                               "text": "asserted with nothing behind it", "evidence": []}])

    report = bind_review(source, gold, review)

    assert report.clause_bindings[0].obligation_id is None
    assert report.clause_bindings[0].reason == UNBOUND_NO_EVIDENCE
    assert report.unbound_clauses == ["f1"]


def test_a_finding_citing_text_not_in_the_contract_is_unbound():
    source, gold = _case()
    review = _review(
        citations=[{"citation_id": "c1", "quote": "a clause that appears nowhere at all"}],
        clauses=[{"finding_id": "f1", "clause_type": "x", "text": "y", "evidence": ["c1"]}],
    )

    report = bind_review(source, gold, review)
    assert report.clause_bindings[0].reason == UNBOUND_UNRESOLVED


def test_evidence_spanning_two_obligations_is_unbound():
    """One finding may not claim two duties at once."""
    source, gold = _case()
    review = _review(
        citations=[
            {"citation_id": "c1", "quote": "engage sub-processors at its own discretion"},
            {"citation_id": "c2", "quote": "On-site inspections and audits by the Controller"},
        ],
        clauses=[{"finding_id": "f1", "clause_type": "everything",
                  "text": "x", "evidence": ["c1", "c2"]}],
    )

    report = bind_review(source, gold, review)
    assert report.clause_bindings[0].reason == UNBOUND_SPLIT


def test_the_unadjudicated_dpa_split_reports_ambiguous_rather_than_guessing():
    """The migration gave both split duties the same span, on purpose.

    Until adjudication sets their boundaries, evidence cannot tell them apart. The
    scorer says so instead of crediting whichever sorts first, which is exactly the
    behaviour that keeps the candidate set from looking more settled than it is.
    """
    source, gold = _case()
    review = _review(
        citations=[{"citation_id": "c1",
                    "quote": "notify the Controller of a personal data breach"}],
        clauses=[{"finding_id": "f1", "clause_type": "data_breach_notification",
                  "text": "x", "evidence": ["c1"]}],
    )

    report = bind_review(source, gold, review)
    assert report.clause_bindings[0].reason == UNBOUND_AMBIGUOUS

    index = build_normalized_index(source)
    assignment = assign_citation(
        "notify the Controller of a personal data breach", index, gold.obligations
    )
    assert assignment.status == "ambiguous_overlap"
    assert set(assignment.candidates) == {"dpa.breach_notification", "dpa.dpia_assistance"}


def test_a_quote_matching_twice_is_ambiguous_not_first_match():
    source = "the same words here. filler. the same words here."
    index = build_normalized_index(source)

    class _O:
        obligation_id, start, end = "case.a", 0, 20

    assignment = assign_citation("the same words here", index, [_O()])
    assert assignment.status == "ambiguous_quote"


def test_a_grounded_quote_outside_every_obligation_earns_no_coverage():
    source, gold = _case()
    review = _review(citations=[{"citation_id": "c1", "quote": "This document is fabricated"}])

    scores = score_obligations(source, gold, review.citations)
    assert scores.unassigned_citations == 1
    assert scores.unsupported_citations == 0
    assert scores.gold_anchor_recall == 0.0


def test_conflicting_risk_severities_are_surfaced_and_first_wins():
    source, gold = _case()
    review = _review(
        citations=[{"citation_id": "c1",
                    "quote": "engage sub-processors at its own discretion"}],
        risk_flags=[
            {"risk_id": "r1", "clause_type": "a", "severity": "high",
             "rationale": "x", "evidence": ["c1"]},
            {"risk_id": "r2", "clause_type": "b", "severity": "low",
             "rationale": "y", "evidence": ["c1"]},
        ],
    )

    report = bind_review(source, gold, review)
    assert report.duplicate_risk_findings == ["dpa.subprocessor_authorization"]
    assert report.conflicting_risk_findings == ["dpa.subprocessor_authorization"]


def test_unknown_and_duplicate_citation_ids_fail_validation():
    with pytest.raises(ValidationError, match="unknown citation ids"):
        _review(clauses=[{"finding_id": "f1", "clause_type": "x",
                          "text": "y", "evidence": ["missing"]}])

    with pytest.raises(ValidationError, match="duplicate citation ids"):
        _review(citations=[{"citation_id": "c1", "quote": "a"},
                           {"citation_id": "c1", "quote": "b"}])
