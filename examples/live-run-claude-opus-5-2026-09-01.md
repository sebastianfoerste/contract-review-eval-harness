# Live model run, 2026-09-01

**Generated from captured output. Do not edit by hand.**

Regenerate with `make live-run-report`. Report digest: `741bfb54ada2f08463ceac5d5fc4a573f8d16ef9555451547d4800e38801a405`.

- Model label: `claude-opus-5`
- Comparison only: true

## Disclosures

- One exploratory run against three synthetic agreements.
- Imported from preserved raw output; provider request id, stop reason and token usage were never recorded and are null.
- Comparison-only: it measures the harness, not the model, and establishes no claim of fitness for contract review.

## One captured output, scored twice

Each pair of rows below scores identical bytes. The only difference is whether
declared clause synonyms were applied, so the delta isolates the scoring rule.

| Case | Aliases | Clause P | Clause R | Clause F1 | Risk P | Risk R | Severity | Span coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| nda | off | 0.500 | 0.545 | 0.522 | 0.33 | 0.50 | 1.00 | 1.000 |
| nda | on | 0.750 | 0.818 | 0.783 | 0.56 | 0.83 | 1.00 | 1.000 |
| saas | off | 0.636 | 0.636 | 0.636 | 0.56 | 0.62 | 0.60 | 1.000 |
| saas | on | 0.818 | 0.818 | 0.818 | 0.67 | 0.75 | 0.67 | 1.000 |
| dpa | off | 0.364 | 0.400 | 0.381 | 0.12 | 0.20 | 1.00 | 0.900 |
| dpa | on | 0.455 | 0.500 | 0.476 | 0.25 | 0.40 | 1.00 | 0.900 |

## Citation grounding

| Case | Grounded | Total | Unsupported |
| --- | ---: | ---: | ---: |
| nda | 12 | 12 | 0 |
| saas | 11 | 11 | 0 |
| dpa | 14 | 14 | 0 |

Grounding is an exact contiguous span of the normalised source.

## Boundary

Single run, single model, three synthetic agreements, one annotator, no blind
adjudication. Nothing here authorises reliance on an AI contract review without
a qualified lawyer confirming every flagged risk and every citation.
