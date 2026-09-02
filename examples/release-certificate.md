# Contract Review Release Certificate

**Suite decision: REJECT**

- Policy: `contract-review-eval.strict-legal-release-policy.v2`
- Cases: 3
- Rejected: 3
- Unsupported citations: 3
- Integrity SHA-256: `cb08c9340dc45ea365d11458f489e703ebafe5df18c5f43f2aa0199e61440092`

## Case decisions

Every column below is a decision input. A case is eligible only when all of
them pass; diagnostics are reported separately and never decide anything.

| Case | Decision | citation.grounding | citation.unsupported | clause.precision | clause.recall | risk.precision | risk.recall | risk.severity | risk.duplicates | risk.conflicts |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dpa | REJECT | 0.88 | 1 | 0.91 | 1.00 | 1.00 | 1.00 | 0.60 | 0 | 0 |
| nda | REJECT | 0.89 | 1 | 0.92 | 1.00 | 0.83 | 0.83 | 0.60 | 0 | 0 |
| saas | REJECT | 0.89 | 1 | 0.92 | 1.00 | 1.00 | 0.88 | 0.57 | 0 | 0 |

## Diagnostics (not decision inputs)

| Case | clause_f1 | risk_f1 | risk_flag_accuracy | risk_false_positives | risk_missed | risk_severity_confusion | span_coverage | span_uncovered_clauses | citation_grounded | citation_total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dpa | 0.95 | 1.00 | 0.60 | 0 | 0 | 3 | 0.70 | 3 | 7 | 8 |
| nda | 0.96 | 0.83 | 0.50 | 1 | 1 | 4 | 0.73 | 3 | 8 | 9 |
| saas | 0.96 | 0.93 | 0.50 | 0 | 1 | 4 | 0.73 | 3 | 8 | 9 |

## Failure register

- `dpa`: citation_grounding_below_100_percent, unsupported_citation_detected, unexpected_clause_extracted, risk_severity_mismatch
- `nda`: citation_grounding_below_100_percent, unsupported_citation_detected, unexpected_clause_extracted, risk_false_positive, expected_risk_missed, risk_severity_mismatch
- `saas`: citation_grounding_below_100_percent, unsupported_citation_detected, unexpected_clause_extracted, expected_risk_missed, risk_severity_mismatch

## Review gate

The certificate evaluates a synthetic benchmark and never authorizes deployment, contract reliance, or autonomous legal review.
