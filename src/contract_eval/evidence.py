"""Bind findings to obligations through their evidence.

A finding is bound when every citation it names resolves to the same obligation. If
its evidence resolves nowhere, resolves ambiguously, or points at two obligations at
once, the finding is unbound and earns nothing. That is the point: a claim about a
clause is only worth what the text it cites can support.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contract_eval.gold_v2 import ExpectedAnswerV2
from contract_eval.obligation_scorer import assign_citation
from contract_eval.review_v2 import ReviewOutputV2
from contract_eval.scorer import build_normalized_index

# Why a finding could not be tied to exactly one obligation.
UNBOUND_NO_EVIDENCE = "no_evidence"
UNBOUND_UNRESOLVED = "evidence_unresolved"
UNBOUND_AMBIGUOUS = "evidence_ambiguous"
UNBOUND_SPLIT = "evidence_spans_multiple_obligations"


@dataclass
class BoundFinding:
    finding_id: str
    obligation_id: str | None
    reason: str | None = None
    severity: str | None = None


@dataclass
class EvidenceReport:
    clause_bindings: list[BoundFinding] = field(default_factory=list)
    risk_bindings: list[BoundFinding] = field(default_factory=list)

    obligation_precision: float = 0.0
    obligation_recall: float = 0.0
    risk_precision: float = 0.0
    risk_recall: float = 0.0
    risk_severity_accuracy: float = 0.0

    unbound_clauses: list[str] = field(default_factory=list)
    unbound_risks: list[str] = field(default_factory=list)
    duplicate_obligation_findings: list[str] = field(default_factory=list)
    duplicate_risk_findings: list[str] = field(default_factory=list)
    conflicting_risk_findings: list[str] = field(default_factory=list)


def _bind(evidence_ids, citations, index, obligations) -> tuple[str | None, str | None]:
    if not evidence_ids:
        return None, UNBOUND_NO_EVIDENCE

    resolved: set[str] = set()
    for citation_id in evidence_ids:
        citation = citations.get(citation_id)
        if citation is None:
            return None, UNBOUND_UNRESOLVED
        assignment = assign_citation(citation.quote, index, obligations)
        if assignment.status == "assigned":
            resolved.add(assignment.obligation_id)
        elif assignment.status in ("ambiguous_quote", "ambiguous_overlap"):
            return None, UNBOUND_AMBIGUOUS
        else:
            return None, UNBOUND_UNRESOLVED

    if len(resolved) > 1:
        return None, UNBOUND_SPLIT
    return resolved.pop(), None


def bind_review(
    source_text: str,
    gold: ExpectedAnswerV2,
    review: ReviewOutputV2,
) -> EvidenceReport:
    index = build_normalized_index(source_text)
    obligations = list(gold.obligations)
    citations = review.citation_by_id()

    report = EvidenceReport()

    for finding in review.clauses:
        obligation_id, reason = _bind(finding.evidence, citations, index, obligations)
        report.clause_bindings.append(
            BoundFinding(finding.finding_id, obligation_id, reason)
        )
        if obligation_id is None:
            report.unbound_clauses.append(finding.finding_id)

    for flag in review.risk_flags:
        obligation_id, reason = _bind(flag.evidence, citations, index, obligations)
        report.risk_bindings.append(
            BoundFinding(flag.risk_id, obligation_id, reason, severity=flag.severity)
        )
        if obligation_id is None:
            report.unbound_risks.append(flag.risk_id)

    bound_clause_ids = [b.obligation_id for b in report.clause_bindings if b.obligation_id]
    report.duplicate_obligation_findings = sorted(
        {o for o in bound_clause_ids if bound_clause_ids.count(o) > 1}
    )

    # First prediction wins, after duplicates and conflicts are surfaced. Deciding by
    # list order without reporting it is how a self-contradicting review scored as
    # agreeing with the gold set.
    predicted_risk: dict[str, str] = {}
    seen_order: list[str] = []
    for binding in report.risk_bindings:
        if binding.obligation_id is None:
            continue
        seen_order.append(binding.obligation_id)
        if binding.obligation_id in predicted_risk:
            if predicted_risk[binding.obligation_id] != binding.severity:
                report.conflicting_risk_findings.append(binding.obligation_id)
            continue
        predicted_risk[binding.obligation_id] = binding.severity
    report.duplicate_risk_findings = sorted(
        {o for o in seen_order if seen_order.count(o) > 1}
    )
    report.conflicting_risk_findings = sorted(set(report.conflicting_risk_findings))

    gold_ids = {o.obligation_id for o in obligations}
    covered = set(bound_clause_ids)
    report.obligation_recall = len(covered & gold_ids) / len(gold_ids) if gold_ids else 1.0
    report.obligation_precision = (
        len(covered & gold_ids) / len(report.clause_bindings)
        if report.clause_bindings else 1.0
    )

    gold_risks = gold.risk_obligations()
    gold_risk_ids = set(gold_risks)
    predicted_ids = set(predicted_risk)
    matched = gold_risk_ids & predicted_ids
    report.risk_precision = len(matched) / len(predicted_ids) if predicted_ids else 1.0
    report.risk_recall = len(matched) / len(gold_risk_ids) if gold_risk_ids else 1.0
    correct = sum(1 for oid in matched if predicted_risk[oid] == gold_risks[oid].severity)
    report.risk_severity_accuracy = correct / len(matched) if matched else 0.0

    return report
