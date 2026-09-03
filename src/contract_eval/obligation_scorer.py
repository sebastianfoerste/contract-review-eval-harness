"""Score a review against atomic obligations, using evidence rather than labels.

Label matching asks whether a review used the gold set's name for a clause. This asks
where the review actually quoted, and which obligation that text belongs to. A review
calling a clause `audits_and_inspections` instead of `audit_rights` is scored the same,
because vocabulary never enters the comparison.

    quote -> every normalised occurrence -> raw span -> unique greatest overlap
               |                                          |
               v                                          v
           0 matches: unsupported                  tie or none: ambiguous
           2+ matches: ambiguous                   one winner: obligation credited
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from contract_eval.gold_v2 import ExpectedAnswerV2, Obligation
from contract_eval.scorer import NormalizedIndex, build_normalized_index, normalize_text


@dataclass
class CitationAssignment:
    """Where one quoted citation landed."""

    quote: str
    status: str  # assigned | unsupported | ambiguous_quote | ambiguous_overlap | unassigned
    raw_span: tuple[int, int] | None = None
    obligation_id: str | None = None
    candidates: list[str] = field(default_factory=list)


@dataclass
class ObligationScores:
    gold_anchor_recall: float
    supported_prediction_rate: float
    covered: list[str]
    uncovered: list[str]
    assignments: list[CitationAssignment]
    unsupported_citations: int
    ambiguous_citations: int
    unassigned_citations: int


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def assign_citation(
    quote: str,
    index: NormalizedIndex,
    obligations: Iterable[Obligation],
) -> CitationAssignment:
    """Assign one quote to at most one obligation.

    A quote that matches the source in more than one place is ambiguous rather than
    credited to whichever came first: the review has not shown which passage it meant,
    and guessing would award evidence the reviewer never gave.

    Where a quote overlaps several obligations, the single greatest overlap wins. An
    exact tie is ambiguous for the same reason.
    """
    spans = index.find_all(normalize_text(quote))
    if not spans:
        return CitationAssignment(quote=quote, status="unsupported")
    if len(spans) > 1:
        return CitationAssignment(quote=quote, status="ambiguous_quote", candidates=[])

    span = spans[0]
    overlaps = [(o.obligation_id, _overlap(span, (o.start, o.end))) for o in obligations]
    positive = sorted(
        ((oid, size) for oid, size in overlaps if size > 0),
        key=lambda pair: (-pair[1], pair[0]),
    )
    if not positive:
        # Grounded in the document but outside every obligation. Still a real
        # quotation, so it is not unsupported; it simply earns no coverage.
        return CitationAssignment(quote=quote, status="unassigned", raw_span=span)

    best_size = positive[0][1]
    winners = [oid for oid, size in positive if size == best_size]
    if len(winners) > 1:
        return CitationAssignment(
            quote=quote, status="ambiguous_overlap", raw_span=span, candidates=winners
        )
    return CitationAssignment(
        quote=quote, status="assigned", raw_span=span, obligation_id=winners[0]
    )


def score_obligations(
    source_text: str,
    gold: ExpectedAnswerV2,
    citations: Iterable,
) -> ObligationScores:
    """Coverage and support, measured through evidence.

    The source is normalised once and the index reused across every citation, so a
    document is not re-scanned per quote.
    """
    index = build_normalized_index(source_text)
    obligations = list(gold.obligations)

    assignments = [assign_citation(c.quote, index, obligations) for c in citations]

    covered_ids = {a.obligation_id for a in assignments if a.status == "assigned"}
    covered = sorted(covered_ids)
    uncovered = sorted(o.obligation_id for o in obligations if o.obligation_id not in covered_ids)

    total = len(obligations)
    assigned = sum(1 for a in assignments if a.status == "assigned")

    return ObligationScores(
        gold_anchor_recall=len(covered) / total if total else 0.0,
        supported_prediction_rate=assigned / len(assignments) if assignments else 0.0,
        covered=covered,
        uncovered=uncovered,
        assignments=assignments,
        unsupported_citations=sum(1 for a in assignments if a.status == "unsupported"),
        ambiguous_citations=sum(
            1 for a in assignments if a.status in ("ambiguous_quote", "ambiguous_overlap")
        ),
        unassigned_citations=sum(1 for a in assignments if a.status == "unassigned"),
    )
