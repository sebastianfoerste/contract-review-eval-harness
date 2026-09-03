"""Compare two independent annotations and record every disagreement.

Agreement statistics are descriptive, never a pass mark. A high kappa on three
synthetic contracts annotated by two people says the two people read them similarly;
it says nothing about whether either reading is correct. The output that matters is
the disagreement ledger, because each entry is a decision someone has to make in
writing.

Obligations are matched by span overlap, not by id. Two annotators working blind will
not choose the same identifiers, and matching on names would manufacture disagreement
where there is none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contract_eval.gold_v2 import ExpectedAnswerV2, Obligation

# Below this share of overlap, two spans are treated as different obligations rather
# than as a boundary disagreement about the same one.
MATCH_THRESHOLD = 0.5

DisagreementKind = Literal[
    "only_in_a", "only_in_b", "boundary", "risk_presence", "severity", "source_category"
]


@dataclass
class Disagreement:
    kind: DisagreementKind
    a_id: str | None
    b_id: str | None
    detail: str


@dataclass
class AgreementReport:
    matched_pairs: list[tuple[str, str]] = field(default_factory=list)
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)

    obligation_agreement: float = 0.0
    exact_risk_agreement: float = 0.0
    severity_agreement: float = 0.0
    weighted_kappa: float | None = None

    def unresolved(self) -> int:
        return len(self.disagreements)


def _iou(a: Obligation, b: Obligation) -> float:
    overlap = max(0, min(a.end, b.end) - max(a.start, b.start))
    union = max(a.end, b.end) - min(a.start, b.start)
    return overlap / union if union else 0.0


def _match(a_set: list[Obligation], b_set: list[Obligation]) -> list[tuple[Obligation, Obligation, float]]:
    """Greedy best-overlap pairing. Each obligation matches at most once."""
    scored = sorted(
        (
            (_iou(a, b), a, b)
            for a in a_set
            for b in b_set
            if _iou(a, b) >= MATCH_THRESHOLD
        ),
        key=lambda t: (-t[0], t[1].obligation_id, t[2].obligation_id),
    )
    used_a: set[str] = set()
    used_b: set[str] = set()
    pairs = []
    for score, a, b in scored:
        if a.obligation_id in used_a or b.obligation_id in used_b:
            continue
        used_a.add(a.obligation_id)
        used_b.add(b.obligation_id)
        pairs.append((a, b, score))
    return pairs


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


def _weighted_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Linearly weighted Cohen's kappa over severity labels.

    Returns None when it is not defined, rather than a number that looks like
    agreement. With fewer than two ratings, or when one annotator used a single label
    throughout, expected agreement is degenerate and kappa is meaningless.
    """
    if len(pairs) < 2:
        return None
    labels = ["low", "medium", "high"]
    n = len(pairs)
    a_counts = {l: sum(1 for a, _ in pairs if a == l) for l in labels}
    b_counts = {l: sum(1 for _, b in pairs if b == l) for l in labels}
    if max(a_counts.values()) == n or max(b_counts.values()) == n:
        return None

    max_distance = len(labels) - 1

    def weight(x: str, y: str) -> float:
        return 1 - abs(_SEVERITY_RANK[x] - _SEVERITY_RANK[y]) / max_distance

    observed = sum(weight(a, b) for a, b in pairs) / n
    expected = sum(
        weight(x, y) * (a_counts[x] / n) * (b_counts[y] / n)
        for x in labels
        for y in labels
    )
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def compare(a: ExpectedAnswerV2, b: ExpectedAnswerV2) -> AgreementReport:
    """Compare two annotations of the same contract."""
    if a.case != b.case:
        raise ValueError(f"annotations describe different cases: {a.case!r} and {b.case!r}")

    report = AgreementReport()
    pairs = _match(list(a.obligations), list(b.obligations))
    matched_a = {p[0].obligation_id for p in pairs}
    matched_b = {p[1].obligation_id for p in pairs}

    report.matched_pairs = [(p[0].obligation_id, p[1].obligation_id) for p in pairs]
    report.only_in_a = sorted(o.obligation_id for o in a.obligations if o.obligation_id not in matched_a)
    report.only_in_b = sorted(o.obligation_id for o in b.obligations if o.obligation_id not in matched_b)

    for oid in report.only_in_a:
        report.disagreements.append(
            Disagreement("only_in_a", oid, None, "annotator B recorded no overlapping obligation")
        )
    for oid in report.only_in_b:
        report.disagreements.append(
            Disagreement("only_in_b", None, oid, "annotator A recorded no overlapping obligation")
        )

    severity_pairs: list[tuple[str, str]] = []
    exact_risk_matches = 0

    for obligation_a, obligation_b, score in pairs:
        if score < 1.0:
            report.disagreements.append(Disagreement(
                "boundary", obligation_a.obligation_id, obligation_b.obligation_id,
                f"spans overlap {score:.2f}: "
                f"A[{obligation_a.start}:{obligation_a.end}] "
                f"B[{obligation_b.start}:{obligation_b.end}]",
            ))

        risk_a, risk_b = obligation_a.risk, obligation_b.risk
        if (risk_a is None) != (risk_b is None):
            flagged = "A" if risk_a else "B"
            report.disagreements.append(Disagreement(
                "risk_presence", obligation_a.obligation_id, obligation_b.obligation_id,
                f"only annotator {flagged} flagged this obligation as a risk",
            ))
            continue
        if risk_a is None:
            exact_risk_matches += 1
            continue

        severity_pairs.append((risk_a.severity, risk_b.severity))
        if risk_a.severity == risk_b.severity:
            exact_risk_matches += 1
        else:
            report.disagreements.append(Disagreement(
                "severity", obligation_a.obligation_id, obligation_b.obligation_id,
                f"A says {risk_a.severity}, B says {risk_b.severity}",
            ))
        if risk_a.source_category != risk_b.source_category:
            report.disagreements.append(Disagreement(
                "source_category", obligation_a.obligation_id, obligation_b.obligation_id,
                f"A rests on {risk_a.source_category}, B on {risk_b.source_category}",
            ))

    total = len(pairs) + len(report.only_in_a) + len(report.only_in_b)
    report.obligation_agreement = len(pairs) / total if total else 0.0
    report.exact_risk_agreement = exact_risk_matches / len(pairs) if pairs else 0.0
    report.severity_agreement = (
        sum(1 for x, y in severity_pairs if x == y) / len(severity_pairs)
        if severity_pairs else 0.0
    )
    report.weighted_kappa = _weighted_kappa(severity_pairs)
    return report


def render_ledger(case: str, report: AgreementReport) -> str:
    """A disagreement ledger, written for the adjudicator."""
    lines = [
        f"# Disagreement ledger: {case}",
        "",
        "Descriptive statistics. They summarise how two readings differ; they do not",
        "establish that either is correct, and they are not a pass mark.",
        "",
        f"- Matched obligations: {len(report.matched_pairs)}",
        f"- Only annotator A: {len(report.only_in_a)}",
        f"- Only annotator B: {len(report.only_in_b)}",
        f"- Obligation agreement: {report.obligation_agreement:.3f}",
        f"- Exact risk agreement: {report.exact_risk_agreement:.3f}",
        f"- Severity agreement: {report.severity_agreement:.3f}",
        f"- Weighted kappa: "
        + (f"{report.weighted_kappa:.3f}" if report.weighted_kappa is not None
           else "not defined for this sample"),
        "",
        f"## Unresolved disagreements: {report.unresolved()}",
        "",
    ]
    if not report.disagreements:
        lines.append("None.")
    else:
        lines += [
            "Every row needs a written adjudication before the gold set can be frozen.",
            "",
            "| Kind | A | B | Detail | Adjudication |",
            "| --- | --- | --- | --- | --- |",
        ]
        for d in report.disagreements:
            lines.append(
                f"| {d.kind} | {d.a_id or '—'} | {d.b_id or '—'} | {d.detail} | |"
            )
    lines.append("")
    return "\n".join(lines)
