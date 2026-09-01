"""Render an evaluation scorecard as markdown."""

from typing import Any

from contract_eval.scorer import CitationScore, ClauseScore


def render(
    case: str,
    clause: ClauseScore,
    risk_accuracy: float,
    citation: CitationScore,
    hallucinations: int,
    scores: dict[str, Any] | None = None,
) -> str:
    """Render one case.

    `scores` carries the full metric dict. It is optional so existing callers keep
    working, but without it the risk section cannot be shown, and risk accuracy alone
    is blind to over-flagging.
    """
    s = scores or {}
    risk_rows = ""
    if s:
        risk_rows = (
            f"| Risk precision | {s['risk_precision']:.2f} | flagged clauses that the gold set treats as risks |\n"
            f"| Risk recall | {s['risk_recall']:.2f} | gold risks the review flagged |\n"
            f"| Risk F1 | {s['risk_f1']:.2f} | harmonic mean of risk precision and recall |\n"
            f"| Severity accuracy | {s['risk_severity_accuracy']:.2f} | correct severity among jointly identified risks |\n"
            f"| Risk false positives | {len(s['risk_false_positives'])} | clauses flagged that the gold set does not treat as risks |\n"
            f"| Risk missed | {len(s['risk_missed'])} | gold risks the review did not flag |\n"
            f"| Duplicate / conflicting flags | {len(s['risk_duplicate_flags'])} / {len(s['risk_conflicting_flags'])} | predictions collapsing onto one clause |\n"
            f"| Span coverage | {s['span_coverage']:.2f} | gold clauses with a grounded citation inside them |\n"
        )

    return f"""# Contract Review Eval Scorecard: {case}

## System under review

Adapter output for the `{case}` case, scored against `expected/{case}.json`.

## Scores

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | {clause.precision:.2f} | predicted clause types that were expected |
| Clause recall | {clause.recall:.2f} | expected clause types that were found |
| Clause F1 | {clause.f1:.2f} | harmonic mean of precision and recall |
{risk_rows}| Citation grounding | {citation.grounding_rate:.2f} | {citation.grounded}/{citation.total} quotes matched as an exact span of the normalised source |
| Hallucination count | {hallucinations} | cited quotes not grounded in the source |
| Risk-flag accuracy (legacy) | {risk_accuracy:.2f} | blind to false positives; excluded from release decisions |

## Two separate gates

The evaluation threshold gate (`demo-regression-policy.v2`) detects regression against
the deliberately imperfect bundled fixture. Passing it means nothing changed
unexpectedly. It does not mean the output is fit for use.

The release certificate is the eligibility decision. A green CI run is not an approved
benchmark result.

## Human review required

This scorecard measures the review method, not a public benchmark. Every flagged risk and
every citation must be confirmed by a qualified lawyer before reliance. A non-zero
hallucination count means at least one citation could not be grounded in the source and
must be rejected outright.

## Failure modes checked

- Over-extraction: clause precision below 1.00.
- Missed clause: clause recall below 1.00.
- Over-flagging: risk precision below 1.00.
- Missed risk: risk recall below 1.00.
- Wrong severity: severity accuracy below 1.00.
- Self-contradiction: conflicting flags above 0.
- Fabricated citation: hallucination count above 0.
"""
