# Contract Review Release Certificate

**Suite decision: REJECT**

- Policy: `contract-review-eval.strict-legal-release-policy.v1`
- Cases: 3
- Rejected: 3
- Unsupported citations: 3
- Integrity SHA-256: `b86dd5ae128fd9d9cd3a87c1f915c8f8ddb6597432826dd18beaa67480b7e002`

## Case decisions

| Case | Decision | Clause F1 | Risk accuracy | Citation grounding | Unsupported citations |
| --- | --- | ---: | ---: | ---: | ---: |
| dpa | REJECT | 0.95 | 0.60 | 0.88 | 1 |
| nda | REJECT | 0.96 | 0.50 | 0.89 | 1 |
| saas | REJECT | 0.96 | 0.50 | 0.89 | 1 |

## Failure register

- `dpa`: unsupported_citation_detected, citation_grounding_below_100_percent, unexpected_clause_extracted, risk_severity_mismatch
- `nda`: unsupported_citation_detected, citation_grounding_below_100_percent, unexpected_clause_extracted, risk_severity_mismatch
- `saas`: unsupported_citation_detected, citation_grounding_below_100_percent, unexpected_clause_extracted, risk_severity_mismatch

## Review gate

The certificate evaluates a synthetic benchmark and never authorizes deployment, contract reliance, or autonomous legal review.
