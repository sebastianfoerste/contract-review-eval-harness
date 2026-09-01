# Live model run, 2026-09-01

| Field | Value |
| --- | --- |
| Model | `claude-opus-5` |
| Output generated | 2026-09-01 |
| Scored | 2026-09-01 |
| Scorer version | 0.4.1 |
| Runs | 1 per case |
| Raw output | [`examples/raw-output/`](raw-output/), hashed in `MANIFEST.json` |

One exploratory run against three synthetic agreements. It measures the harness, not
the model. It does not validate the gold sets and does not establish that any model is
fit for contract review.

## Controlled comparison: one output, two scorers

The raw adapter output was captured once and scored twice, with clause aliasing
disabled and enabled. The bytes being scored are identical in both rows, so the
difference isolates the scoring rule.

| Case | Aliases | Clause precision | Clause recall | Clause F1 | Risk precision | Risk recall | Severity accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| NDA | off | 0.500 | 0.545 | 0.522 | 0.33 | 0.50 | 1.00 |
| NDA | on | 0.750 | 0.818 | 0.783 | 0.56 | 0.83 | 1.00 |
| SaaS | off | 0.636 | 0.636 | 0.636 | 0.56 | 0.62 | 0.60 |
| SaaS | on | 0.818 | 0.818 | 0.818 | 0.67 | 0.75 | 0.67 |
| DPA | off | 0.364 | 0.400 | 0.381 | 0.12 | 0.20 | 1.00 |
| DPA | on | 0.455 | 0.500 | 0.476 | 0.25 | 0.40 | 1.00 |

Aliasing raises every score, confirming that label normalisation was suppressing real
agreement. It does not eliminate the problem: recall reaches at most 0.818, and the
DPA stays at 0.500.

## Why aliasing does not solve it

The alias map was written after observing one earlier run's vocabulary. This run used
different labels again, so the map does not transfer:

- `data_breach_notification` here, `personal_data_breach_notification` before.
- `processing_instructions` here, `subject_matter_and_instructions` before.
- `information_security` here, `security_of_processing` before.

One mismatch is not a naming difference at all. On the DPA the model returned
`data_breach_notification` and `dpia_assistance` as two clauses where the gold set
carries a single `breach_and_dpia_assistance`. A one-to-one alias map cannot express a
one-to-many split, so that clause is scored as missed no matter how many synonyms are
added.

Expanding the alias map after each run would fit the benchmark to whatever the last
model said, which is the failure this repository exists to expose. The durable fix is
to stop matching on labels: anchor each gold clause to a span of the source document
and score whether the review covered that span. That is not implemented.

## Citation grounding

| Case | Citations | Grounded | Unsupported |
| --- | ---: | ---: | ---: |
| NDA | 12 | 12 | 0 |
| SaaS | 11 | 11 | 0 |
| DPA | 14 | 14 | 0 |

This run was scored under the stricter rule introduced in 0.4.1: a citation must match
a contiguous span of the normalised source. The previous rule accepted 85 percent
unordered token overlap, which would accept a reordered or partly substituted quote.
Every citation in this run passes the stricter test.

That is the strongest observation available here, and it remains narrow: 37 citations
across three synthetic documents in a single run.

## Severity

Severity accuracy is measured only on risks both the gold set and the review flagged,
so a severity mistake stays distinguishable from a missed risk. On the clauses it did
identify, the model matched the gold severity on every NDA and DPA flag, and on two of
three SaaS flags.

Risk precision below 1.0 in every row means the model flagged clauses the gold set does
not treat as risks. Whether those are false positives or gold-set omissions has not
been adjudicated, and one annotator wrote both the gold set and this analysis.

## Boundary

Single run, single model, three synthetic agreements, one annotator, no blind
adjudication. Nothing here authorises reliance on an AI contract review without a
qualified lawyer confirming every flagged risk and every citation.
