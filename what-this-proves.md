# What this proves

Top firms do not adopt legal AI because it generates output. They adopt it when someone can
show the output is trustworthy and prove it under scrutiny. This repo is that proof, built
for the post-sales / Legal Engineer side of the work.

| Feature | Responsibility it demonstrates |
| --- | --- |
| Expected answer set (`expected/<case>.json`) | Quality defined against a gold standard, not asserted. |
| Clause precision / recall / F1 | Catching both over-extraction and missed clauses. |
| Risk-flag accuracy | Checking not just *that* a risk was flagged but at the *right severity*. |
| Citation grounding (verbatim check) | The trust question for legal AI: is the cited text actually in the document? |
| Hallucination count | Fabricated citations counted as a first-class failure, not hidden in prose. |
| Deterministic stub + optional `--live` | Reproducible evaluation a reviewer can run with no API key. |
| Scorecard ending in "human review required" | The review gate stays explicit; the harness informs a lawyer, never replaces one. |

The shipped fixtures are intentionally imperfect. A harness that only ever prints 1.00 is
theatre. This one prints 0.83 / 0.50 / 0.80 and a hallucination count of 1 — and shows
exactly which clause, which severity, and which quote failed.
