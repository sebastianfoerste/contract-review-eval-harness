# Sample output: NDA scorecard

Produced by `make demo` (`uv run python -m contract_eval evaluate --case nda`). The stub
model output is deliberately imperfect; this is the harness catching it.

```
# Contract Review Eval Scorecard: nda

## Scores

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.83 | predicted clause types that were expected |
| Clause recall | 1.00 | expected clause types that were found |
| Clause F1 | 0.91 | harmonic mean of precision and recall |
| Risk-flag accuracy | 0.50 | risky clauses flagged at the expected severity |
| Citation grounding | 0.80 | 4/5 quotes grounded in the source (exact match or 85%+ token overlap) |
| Hallucination count | 1 | cited quotes not grounded in the source |
```

Reading it: the model found every required clause (recall 1.00) but invented a sixth
(`indemnification`), dragging precision to 0.83. It flagged the perpetual `term` correctly
as high, but under-called the overbroad `definition` as low instead of medium (risk
accuracy 0.50). And one of its five citations — a renewal clause — is not in the contract
at all, so grounding is 0.80 and the hallucination count is 1.

The take-away for a reviewer: this output is usable as a first pass, but the flagged risks
and citations must be confirmed by a lawyer, and the hallucinated citation must be rejected.
