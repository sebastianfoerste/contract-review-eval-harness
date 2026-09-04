"""Upgrade v1 artifacts into the v2 representation.

The harness carried two parallel worlds: a v1 review and a v2 review, a v1 gold set and
a v2 gold set, with conversion logic living in scripts so only fixtures could cross
between them. A real v1 review, including every legacy capture, could not enter the
evidence-bound path at all.

Treating v1 as an input format rather than a parallel system removes that. There is one
internal representation, and v1 is upgraded at the boundary.

The upgrade is lossy in one direction only, and deliberately so: v1 has no citation ids
and no evidence links, so they are synthesised from the single thing v1 uses to relate a
finding to a quote, its `clause_type`. A finding whose clause type matches no citation
gets no evidence, which is the honest result. In v1 that assertion had nothing behind it
either; v2 simply stops hiding it.
"""

from __future__ import annotations

from contract_eval.gold_v2 import ExpectedAnswerV2
from contract_eval.models import ExpectedAnswer, ReviewOutput
from contract_eval.review_v2 import ReviewOutputV2
from contract_eval.scorer import build_normalized_index, normalize_text


def upgrade_review(review: ReviewOutput) -> ReviewOutputV2:
    """Give a v1 review the ids and evidence links the v2 scorer needs."""
    citations = []
    by_clause: dict[str, list[str]] = {}
    for index, citation in enumerate(review.citations, start=1):
        citation_id = f"c{index}"
        citations.append({"citation_id": citation_id, "quote": citation.quote})
        by_clause.setdefault(citation.clause_type, []).append(citation_id)

    return ReviewOutputV2.model_validate({
        "schema": "contract-review-eval.review-output.v2",
        "citations": citations,
        "clauses": [
            {
                "finding_id": f"f{index}",
                "clause_type": clause.clause_type,
                "text": clause.text,
                "evidence": by_clause.get(clause.clause_type, []),
            }
            for index, clause in enumerate(review.clauses, start=1)
        ],
        "risk_flags": [
            {
                "risk_id": f"r{index}",
                "clause_type": flag.clause_type,
                "severity": flag.severity,
                "rationale": flag.rationale,
                "evidence": by_clause.get(flag.clause_type, []),
            }
            for index, flag in enumerate(review.risk_flags, start=1)
        ],
        "abstentions": [
            {
                "abstention_id": f"a{index}",
                "clause_type": item.clause_type,
                "reason": item.reason,
                "evidence": by_clause.get(item.clause_type, []),
            }
            for index, item in enumerate(review.abstentions, start=1)
        ],
    })


class UpgradeError(RuntimeError):
    """A v1 artifact cannot be expressed in the v2 representation."""


def upgrade_gold(
    case: str,
    gold: ExpectedAnswer,
    source_text: str,
    *,
    annotator_id: str = "annotator-a",
    legal_position_date: str = "2026-09-04",
) -> ExpectedAnswerV2:
    """Locate each v1 clause in the raw source and express it as an obligation.

    v1 anchors were written to match normalised text, so a raw search fails wherever a
    clause wraps a line. Matching normalised and mapping back through the index is the
    only way to recover the offsets the clause actually occupies.
    """
    index = build_normalized_index(source_text)
    aliases_by_target: dict[str, list[str]] = {}
    for alias, target in gold.clause_aliases.items():
        aliases_by_target.setdefault(target, []).append(alias)

    obligations = []
    for clause in gold.clause_types:
        anchor = gold.clause_anchors.get(clause)
        if not anchor:
            raise UpgradeError(f"{case}.{clause}: no anchor to locate the clause")
        spans = index.find_all(normalize_text(anchor))
        if len(spans) != 1:
            raise UpgradeError(
                f"{case}.{clause}: anchor matches {len(spans)} places, expected exactly one"
            )
        start, end = spans[0]

        severity = gold.risk_flags.get(clause)
        risk = None
        if severity:
            risk = {
                "severity": severity,
                "rationale": gold.severity_rationale[clause],
                # v1 recorded no provenance for a severity. Claiming it rests on law
                # would invent a citation, so it is marked as judgment until an
                # annotator says otherwise.
                "source_category": "legal_judgment",
                "source_reference": None,
            }

        obligations.append({
            "obligation_id": f"{case}.{clause}",
            "label": clause.replace("_", " ").title(),
            "description": f"Upgraded from v1 clause {clause}.",
            "start": start,
            "end": end,
            "quote": source_text[start:end],
            "aliases": sorted(aliases_by_target.get(clause, [])),
            "risk": risk,
        })

    context = gold.review_context
    return ExpectedAnswerV2.model_validate({
        "schema": "contract-review-eval.expected-answer.v2",
        "case": case,
        "review_context": {
            "party": context.party if context else "unspecified",
            "commercial_perspective": "Upgraded from a v1 gold set.",
            "governing_law": context.governing_law if context else "unspecified",
            "jurisdiction": "Germany",
            "objective": context.objective if context else "unspecified",
            "risk_appetite": context.risk_appetite if context else "conservative",
            "playbook_id": None,
            "legal_position_date": legal_position_date,
            "annotator_id": annotator_id,
            "annotation_status": "candidate",
            "adjudication_status": "not_started",
        },
        "comment": (
            "Upgraded from the v1 gold set. Candidate, not authoritative: severities "
            "carry over from a single annotator and their provenance is unrecorded."
        ),
        "thresholds": dict(gold.thresholds),
        "obligations": obligations,
    })
