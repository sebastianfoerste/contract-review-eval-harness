# Contract Review Eval Scorecard: nda

## System under review

Adapter output for the `nda` case, scored against `expected/nda.json`.

## Scores

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.83 | predicted clause types that were expected |
| Clause recall | 1.00 | expected clause types that were found |
| Clause F1 | 0.91 | harmonic mean of precision and recall |
| Risk-flag accuracy | 0.50 | risky clauses flagged at the expected severity |
| Citation grounding | 0.80 | 4/5 quotes grounded in the source (exact match or 85%+ token overlap) |
| Hallucination count | 1 | cited quotes not grounded in the source |

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
