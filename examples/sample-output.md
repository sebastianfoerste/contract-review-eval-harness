# Sample output: NDA scorecard

Produced by `make demo` (`uv run python -m contract_eval evaluate --case nda`). The stub
model output is deliberately imperfect; this is the harness catching it.

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

Reading it: the model found every expected clause (recall 1.00) but invented a twelfth
(`indemnification`), so precision is 0.92. It flagged the perpetual `term`, the residuals
clause and the over-broad `definition` at the expected severity, but rated the consent
condition on compelled disclosure `medium` and the free assignment to a competitor `low`
where the answer set says `high` (severity accuracy 0.60). It also flagged `governing_law`,
which the answer set does not treat as a risk, and missed the `notices` risk. And one of its
nine citations, a deemed-delivery rule for notices, is not in the contract at all, so
grounding is 0.89 and the hallucination count is 1.

The take-away for a reviewer: this output is usable as a first pass, but the flagged risks
and citations must be confirmed by a lawyer, and the hallucinated citation must be rejected.
