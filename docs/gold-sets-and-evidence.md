# Gold sets, evidence-bound scoring and schema v2

Moved from the README.

## Use cases

Thirty-two clause types across three agreements:

- **NDA** — definition, confidentiality, term, return/destruction, governing law, permitted
  disclosure, residual knowledge, no licence, injunctive relief, assignment, notices.
- **SaaS agreement** — service levels, data protection, limitation of liability, term,
  auto-renewal, sub-processors, security, IP and model training, indemnity, fees, data
  export on termination.
- **Data processing agreement** — Art. 28(3) lit. a to h GDPR, Chapter V transfers,
  governing law.

Each gold set records a `severity_rationale` naming why every flag carries its severity,
so the calibration can be challenged rather than assumed, and a `clause_aliases` map
declaring synonyms for the same clause so that vocabulary is not scored as legal error.
The provisions those rationales cite are listed in the
[legal currency ledger](legal-currency.md), with the official source each was checked
against, the date it was last verified and what is pending.
Both fields are typed and validated: unknown keys are rejected, and every risk flag must
carry exactly one rationale. Alias validation is structural only and cannot establish
that an alias is a genuine synonym, which is why they are manually reviewed. Some clauses in each agreement
are deliberately unremarkable: a reviewer who flags them is producing false positives.

Every case is built so that clause coverage and legal judgment come apart. The offline
adapter reaches 0.95 to 0.96 clause F1 on all three — it finds every expected clause —
against 0.57 to 0.60 severity accuracy. On the DPA it rates the exclusion of on-site inspections and a transfer clause
carrying no Chapter V mechanism as low risk; on the SaaS agreement it rates a perpetual
licence to train models on Customer Personal Data and a reversed IP indemnity as low
risk; on the NDA it under-rates a consent condition on legally compelled disclosure and a
free assignment to a competitor.
A reviewer reading only the coverage number would approve all three.

Adding a fourth contract type means adding four files and one entry in
[`src/contract_eval/cases.py`](../src/contract_eval/cases.py); no consumer hardcodes
the case set. The [annotation guideline](ANNOTATION_GUIDELINE.md) records how
clause types are chosen, how severities are calibrated, and why a stub fixture is
never tuned to clear a threshold.

## One representation, two input formats

The harness briefly carried two parallel worlds: a v1 review and a v2 review, a v1 gold
set and a v2 gold set, with conversion trapped in scripts so only fixtures could cross
between them. A real v1 review could not enter the evidence path at all.

`contract_eval.upgrade` makes v1 an input format rather than a parallel system. A v1
review gains synthesised citation ids and evidence links inferred from its `clause_type`;
a v1 gold set gains raw offsets located through the normalised index. Both then run the
same scorer.

The upgrade is honest about what v1 did not record. A v1 severity has no provenance, so
it upgrades to `legal_judgment` rather than claiming to rest on a provision, and a
finding whose clause type matches no citation gets no evidence, which is what it always
had.

## The evidence-bound path

```bash
uv run python -m contract_eval evaluate-obligations --case all
```

Scores a review through cited evidence rather than clause labels. A finding binds to an
obligation only when the citations it names resolve to that obligation's span, so what
a review calls a clause cannot earn or lose it credit, and an assertion with nothing
quoted behind it is visibly unbound.

It prints no release decision. Policy v3 refuses to certify against a single-annotator
gold set, and the scorecard says so rather than omitting the section.

## Gold schema v2, in preparation

Schema v2 replaces named clauses with atomic obligations anchored to raw character
offsets, so coverage no longer depends on what a review calls anything. Candidate
obligations live in [`annotations/drafts/`](../annotations/) and are validated against
their source on every run by `make gold-v2-check`: 33 obligations, every offset
resolving to the exact recorded quote.

They are **not** authoritative. The candidates were derived by one annotator, and their
severities carried over from that same annotator, so statistics computed against them
would measure a set against itself. `expected/*.json` under schema v1 remains the gold
set until a second qualified reviewer has annotated the same contracts blind and every
disagreement has been adjudicated. That reviewer is a hard external dependency.

