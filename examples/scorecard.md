# Contract Review Eval Scorecard: nda

## System under review

Adapter output for the `nda` case, scored against `expected/nda.json`.

## Scores

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.92 | predicted clause types that were expected |
| Clause recall | 1.00 | expected clause types that were found |
| Clause F1 | 0.96 | harmonic mean of precision and recall |
| Risk precision | 0.83 | flagged clauses that the gold set treats as risks |
| Risk recall | 0.83 | gold risks the review flagged |
| Risk F1 | 0.83 | harmonic mean of risk precision and recall |
| Severity accuracy | 0.60 | correct severity among jointly identified risks |
| Risk false positives | 1 | clauses flagged that the gold set does not treat as risks |
| Risk missed | 1 | gold risks the review did not flag |
| Duplicate / conflicting flags | 0 / 0 | predictions collapsing onto one clause |
| Span coverage | 0.73 | gold clauses with a grounded citation inside them |
| Citation grounding | 0.89 | 8/9 quotes matched as an exact span of the normalised source |
| Hallucination count | 1 | cited quotes not grounded in the source |
| Risk-flag accuracy (legacy) | 0.50 | blind to false positives; excluded from release decisions |

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
