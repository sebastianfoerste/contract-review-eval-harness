"""Render an evaluation scorecard as markdown. Mirrors the legal-rag-evals scorecard shape."""

from contract_eval.scorer import CitationScore, ClauseScore


def render(
    case: str,
    clause: ClauseScore,
    risk_accuracy: float,
    citation: CitationScore,
    hallucinations: int,
) -> str:
    return f"""# Contract Review Eval Scorecard: {case}

## System under review

Adapter output for the `{case}` case, scored against `expected/{case}.json`.

## Scores

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | {clause.precision:.2f} | predicted clause types that were expected |
| Clause recall | {clause.recall:.2f} | expected clause types that were found |
| Clause F1 | {clause.f1:.2f} | harmonic mean of precision and recall |
| Risk-flag accuracy | {risk_accuracy:.2f} | risky clauses flagged at the expected severity |
| Citation grounding | {citation.grounding_rate:.2f} | {citation.grounded}/{citation.total} quotes grounded in the source (exact match or 85%+ token overlap) |
| Hallucination count | {hallucinations} | cited quotes not grounded in the source |

## Human review required

This scorecard measures the review method, not a public benchmark. Every flagged risk and
every citation must be confirmed by a qualified lawyer before reliance. A non-zero
hallucination count means at least one citation could not be grounded in the source and
must be rejected outright.

## Failure modes checked

- Over-extraction: clause precision below 1.00.
- Missed clause: clause recall below 1.00.
- Wrong severity: risk-flag accuracy below 1.00.
- Fabricated citation: hallucination count above 0.
"""
