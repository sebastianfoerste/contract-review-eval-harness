# Live model run — 2026-08-28

| Field | Value |
| --- | --- |
| Model | `claude-opus-4-8` |
| Date (UTC) | 2026-08-28 |
| Harness version | 0.4.0 |
| Runs | 1 per case |
| Gold sets | 32 clause types across three synthetic agreements |

Live output is non-deterministic. This is one run, not a benchmark, and it is not
evidence that any model is fit for contract review. It is recorded because the run
exposed a defect in the harness.

## What the run found in the harness

The first pass scored the model as failing. It was not failing; the harness was
measuring the wrong thing.

| Case | Clause F1 before | Clause F1 after | Risk accuracy before | Risk accuracy after |
| --- | ---: | ---: | ---: | ---: |
| NDA | 0.545 | 0.909 | 0.67 | 0.83 |
| SaaS | 0.818 | 0.909 | 0.50 | 0.62 |
| DPA | 0.400 | 1.000 | 0.00 | 1.00 |

Nothing about the model changed between the two columns. The model had found every
clause in all three agreements on the first pass, and named them in its own
vocabulary: `no_licence` for `no_license`, `sub_processors` for `subprocessors`,
`permitted_disclosures` for the singular, `audits_and_inspections` for `audit_rights`.
Scoring string equality of taxonomy labels reported a correct review as a total
failure — on the DPA, a review that matched the gold set on every clause and every
severity scored 0.40 and 0.00.

The fix is a `clause_aliases` map declared in each gold set, mapping a synonym onto
the gold set's own name for the same clause of the same document. An alias never maps
onto a different clause, and a test enforces that. The stub baseline is unchanged,
because the stub already used canonical names.

## Scores after the fix

| Case | Precision | Recall | F1 | Risk accuracy | Citations grounded | Unsupported |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| NDA | 0.909 | 0.909 | 0.909 | 0.833 | 6/6 | 0 |
| SaaS | 0.909 | 0.909 | 0.909 | 0.625 | 9/9 | 0 |
| DPA | 1.000 | 1.000 | 1.000 | 1.000 | 6/6 | 0 |

Two observations worth recording, both narrow:

**No fabricated citations.** Every quote in all three reviews was grounded in the
source document. The offline stub fixture deliberately fabricates one per case; this
run fabricated none.

**Independent agreement on the DPA severities.** The model assigned `high` to
sub-processor appointment, indefinite retention, excluded audit rights and the
transfer clause with no Chapter V mechanism, and `medium` to the fourteen day breach
window — matching the human-authored `_severity_rationale` on every flag. That is
corroboration of the gold set's calibration by an independent reviewer, not proof
that either is correct.

The SaaS risk accuracy of 0.625 is the weakest result: the model did not reach the
gold severity on three of eight flags.

## Boundary

One run, one model, three synthetic agreements, no second annotator. Nothing here
supports a claim that a model is safe for contract review, and nothing here
authorises reliance on an AI review without a qualified lawyer confirming every
flagged risk and every citation.
