# Contract Review Release Certificate

**Suite decision: REJECT**

- Policy: `contract-review-eval.strict-legal-release-policy.v1`
- Cases: 2
- Rejected: 2
- Unsupported citations: 2
- Integrity SHA-256: `9e17c8a61c64ea145e02482c773477d426931b987996a79bb8695a412a149fa1`

## Case decisions

| Case | Decision | Clause F1 | Risk accuracy | Citation grounding | Unsupported citations |
| --- | --- | ---: | ---: | ---: | ---: |
| nda | REJECT | 0.91 | 0.50 | 0.80 | 1 |
| saas | REJECT | 0.91 | 0.50 | 0.80 | 1 |

## Failure register

- `nda`: unsupported_citation_detected, citation_grounding_below_100_percent, unexpected_clause_extracted, risk_severity_mismatch
- `saas`: unsupported_citation_detected, citation_grounding_below_100_percent, unexpected_clause_extracted, risk_severity_mismatch

## Review gate

The certificate evaluates a synthetic benchmark and never authorizes deployment, contract reliance, or autonomous legal review.
