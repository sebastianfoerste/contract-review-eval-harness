"""Release policy v3: eligibility decided on evidence-bound findings.

v3 is defined here but cannot certify anything yet, and that is deliberate. It scores
against atomic obligations, and the only obligation sets that exist are candidates
derived by one annotator from that annotator's own v1 gold. Certifying against them
would produce a stricter-looking instrument whose stricter judgment is still a single
unreviewed opinion.

`evaluate_v3` therefore refuses any gold set whose annotation status is not `frozen`
and whose adjudication is not `complete`. The refusal is the feature: it is what stops
the machinery being switched on before the second annotator exists.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from contract_eval.evidence import EvidenceReport
from contract_eval.gold_v2 import ExpectedAnswerV2

POLICY_ID = "contract-review-eval.strict-legal-release-policy.v3"
CERTIFICATE_SCHEMA = "contract-review-eval.release-certificate.v4"


class GoldNotAdjudicated(RuntimeError):
    """The gold set has not completed blind annotation and adjudication."""


class RequirementV3(NamedTuple):
    requirement_id: str
    metric: str
    comparator: str  # gte | empty
    threshold: float | None
    failure_class: str  # blocker | review_item
    failure_code: str
    description: str


REQUIREMENTS: tuple[RequirementV3, ...] = (
    RequirementV3(
        "citation.unsupported", "unsupported_citations", "empty", None, "blocker",
        "unsupported_citation_detected",
        "No citation may quote text absent from the source document.",
    ),
    RequirementV3(
        "obligation.precision", "obligation_precision", "gte", 1.0, "review_item",
        "unexpected_obligation_reported",
        "Every reported clause must bind to a declared obligation.",
    ),
    RequirementV3(
        "obligation.recall", "obligation_recall", "gte", 1.0, "review_item",
        "expected_obligation_missed",
        "Every declared obligation must be covered by bound evidence.",
    ),
    RequirementV3(
        "risk.precision", "risk_precision", "gte", 1.0, "review_item",
        "risk_false_positive",
        "No obligation may be flagged that the gold set does not treat as a risk.",
    ),
    RequirementV3(
        "risk.recall", "risk_recall", "gte", 1.0, "review_item",
        "expected_risk_missed",
        "Every gold risk must be flagged.",
    ),
    RequirementV3(
        "risk.severity", "risk_severity_accuracy", "gte", 1.0, "review_item",
        "risk_severity_mismatch",
        "Every jointly identified risk must carry the gold severity.",
    ),
    RequirementV3(
        "evidence.clauses_bound", "unbound_clauses", "empty", None, "review_item",
        "unbound_clause_evidence",
        "Every clause finding must resolve to exactly one obligation.",
    ),
    RequirementV3(
        "evidence.risks_bound", "unbound_risks", "empty", None, "review_item",
        "unbound_risk_evidence",
        "Every risk finding must resolve to exactly one obligation.",
    ),
    RequirementV3(
        "obligation.duplicates", "duplicate_obligation_findings", "empty", None,
        "review_item", "duplicate_obligation_findings",
        "No two clause findings may bind to the same obligation.",
    ),
    RequirementV3(
        "risk.duplicates", "duplicate_risk_findings", "empty", None, "review_item",
        "duplicate_risk_findings",
        "No two risk findings may bind to the same obligation.",
    ),
    RequirementV3(
        "risk.conflicts", "conflicting_risk_findings", "empty", None, "review_item",
        "conflicting_risk_findings",
        "One obligation may not carry contradictory severities.",
    ),
)


def gold_is_certifiable(gold: ExpectedAnswerV2) -> bool:
    context = gold.review_context
    return (
        context.annotation_status == "frozen"
        and context.adjudication_status == "complete"
    )


def _satisfied(requirement: RequirementV3, value: Any) -> bool:
    if requirement.comparator == "gte":
        return float(value) >= float(requirement.threshold)
    if requirement.comparator == "empty":
        return not value
    raise ValueError(f"unknown comparator: {requirement.comparator}")


def evaluate_v3(
    gold: ExpectedAnswerV2,
    report: EvidenceReport,
    *,
    unsupported_citations: int = 0,
) -> dict[str, Any]:
    """Decide eligibility under v3, or refuse if the gold is not adjudicated."""
    if not gold_is_certifiable(gold):
        raise GoldNotAdjudicated(
            f"gold set for {gold.case!r} is annotation_status="
            f"{gold.review_context.annotation_status!r} and adjudication_status="
            f"{gold.review_context.adjudication_status!r}; policy v3 certifies only a "
            "gold set that has completed blind second annotation and adjudication"
        )

    metrics = {
        "unsupported_citations": unsupported_citations,
        "obligation_precision": report.obligation_precision,
        "obligation_recall": report.obligation_recall,
        "risk_precision": report.risk_precision,
        "risk_recall": report.risk_recall,
        "risk_severity_accuracy": report.risk_severity_accuracy,
        "unbound_clauses": report.unbound_clauses,
        "unbound_risks": report.unbound_risks,
        "duplicate_obligation_findings": report.duplicate_obligation_findings,
        "duplicate_risk_findings": report.duplicate_risk_findings,
        "conflicting_risk_findings": report.conflicting_risk_findings,
    }

    blockers, review_items = [], []
    for requirement in REQUIREMENTS:
        if _satisfied(requirement, metrics[requirement.metric]):
            continue
        (blockers if requirement.failure_class == "blocker" else review_items).append(
            requirement.failure_code
        )

    if blockers:
        decision = "REJECT"
    elif review_items:
        decision = "HUMAN_REVIEW_REQUIRED"
    else:
        decision = "PILOT_ELIGIBLE"

    return {
        "schema": CERTIFICATE_SCHEMA,
        "policy_id": POLICY_ID,
        "case": gold.case,
        "decision": decision,
        "blockers": blockers,
        "review_items": review_items,
        "scores": metrics,
    }
