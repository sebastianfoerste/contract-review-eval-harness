# Sample output: NDA scorecard

Produced by `make demo` (`uv run python -m contract_eval evaluate --case nda`). The stub
model output is deliberately imperfect; this is the harness catching it. The block below
is the Scores table from the committed `examples/scorecard.md`.

```
# Contract Review Eval Scorecard: nda

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
```

Reading it: the model found every required clause (recall 1.00) but invented a twelfth
(`indemnification`), dragging precision to 0.92. It flagged five of the six gold risks,
missed `notices` (risk recall 0.83) and flagged `governing_law`, which the gold answer
does not treat as a risk (risk precision 0.83). Of the five risks flagged on both sides,
three carry the expected severity: `term` and `residual_knowledge` as high and
`definition` as medium. It under-called `assignment` as low and `permitted_disclosure` as
medium; the gold answer rates both high (severity accuracy 0.60). The legacy risk-flag
accuracy of 0.50 counts the three of six gold flags predicted at the expected severity.
And one of its nine citations, a deemed-delivery rule for notices, is not in the contract
at all, so grounding is 0.89 and the hallucination count is 1. The eight grounded
citations fall inside eight of the eleven gold clauses (span coverage 0.73).

The take-away for a reviewer: the release certificate (`examples/release-certificate.md`)
rates this output REJECT. The fabricated citation is a blocker on its own, and the
certificate also registers the invented clause, the over-flag, the missed risk and the
severity errors. Every flagged risk and every citation must be confirmed by a lawyer before
reliance.
