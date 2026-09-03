"""Policy v3 exists but must not certify against an unadjudicated gold set."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from contract_eval.evidence import EvidenceReport
from contract_eval.gold_v2 import ExpectedAnswerV2
from contract_eval.policy_v3 import (
    REQUIREMENTS,
    GoldNotAdjudicated,
    evaluate_v3,
    gold_is_certifiable,
)


def _candidate():
    return json.loads(Path("annotations/drafts/dpa.candidate.v2.json").read_text())


def _frozen_gold():
    """A gold set that has completed the process, for exercising the policy itself."""
    raw = deepcopy(_candidate())
    raw["review_context"]["annotation_status"] = "frozen"
    raw["review_context"]["adjudication_status"] = "complete"
    return ExpectedAnswerV2.model_validate(raw)


def _clean_report():
    return EvidenceReport(
        obligation_precision=1.0, obligation_recall=1.0,
        risk_precision=1.0, risk_recall=1.0, risk_severity_accuracy=1.0,
    )


def test_every_committed_candidate_set_is_refused():
    """The gate, asserted on the real files rather than a fixture."""
    for case in ("nda", "saas", "dpa"):
        gold = ExpectedAnswerV2.model_validate(
            json.loads(Path(f"annotations/drafts/{case}.candidate.v2.json").read_text())
        )
        assert not gold_is_certifiable(gold)
        with pytest.raises(GoldNotAdjudicated, match="blind second annotation"):
            evaluate_v3(gold, _clean_report())


def test_a_partially_completed_gold_set_is_still_refused():
    """Freezing without adjudicating, or the reverse, is not enough."""
    for status, adjudication in (("frozen", "in_progress"), ("candidate", "complete")):
        raw = deepcopy(_candidate())
        raw["review_context"]["annotation_status"] = status
        raw["review_context"]["adjudication_status"] = adjudication
        gold = ExpectedAnswerV2.model_validate(raw)

        with pytest.raises(GoldNotAdjudicated):
            evaluate_v3(gold, _clean_report())


def test_an_adjudicated_gold_set_can_reach_pilot_eligible():
    result = evaluate_v3(_frozen_gold(), _clean_report())

    assert result["decision"] == "PILOT_ELIGIBLE"
    assert result["policy_id"].endswith("policy.v3")
    assert result["schema"].endswith("certificate.v4")


def test_every_requirement_fails_in_isolation():
    gold = _frozen_gold()

    for requirement in REQUIREMENTS:
        report = _clean_report()
        unsupported = 0
        if requirement.metric == "unsupported_citations":
            unsupported = 1
        elif requirement.comparator == "gte":
            setattr(report, requirement.metric, 0.5)
        else:
            setattr(report, requirement.metric, ["something"])

        result = evaluate_v3(gold, report, unsupported_citations=unsupported)

        if requirement.failure_class == "blocker":
            assert result["decision"] == "REJECT", requirement.requirement_id
            assert requirement.failure_code in result["blockers"]
        else:
            assert result["decision"] == "HUMAN_REVIEW_REQUIRED", requirement.requirement_id
            assert requirement.failure_code in result["review_items"]


def test_unbound_evidence_prevents_eligibility():
    gold = _frozen_gold()

    report = _clean_report()
    report.unbound_clauses = ["f1"]
    result = evaluate_v3(gold, report)

    assert result["decision"] == "HUMAN_REVIEW_REQUIRED"
    assert "unbound_clause_evidence" in result["review_items"]


def test_unsupported_citation_is_a_hard_blocker():
    result = evaluate_v3(_frozen_gold(), _clean_report(), unsupported_citations=1)

    assert result["decision"] == "REJECT"
    assert "unsupported_citation_detected" in result["blockers"]
