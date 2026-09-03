# Annotations

## Status

The authoritative gold sets remain `expected/*.json` under schema v1. Nothing in this
directory decides anything yet.

| Artifact | Status |
| --- | --- |
| `drafts/*.candidate.v2.json` | Candidate. Single annotator, mechanically derived offsets. |
| `pack/` | Built, not sent. Transmission requires explicit approval. |
| Second annotation | **Not started.** Hard external dependency. |
| Adjudication tooling | Implemented and tested. Waiting on a return to process. |
| Evidence-bound scoring | Implemented. Inactive: policy v3 refuses candidate gold. |
| Policy v3 / certificate v4 | Defined. Cannot certify until gold is frozen and adjudicated. |
| Adjudication | Not started. |

## Why the candidates are not gold

The candidate obligations were derived from the v1 gold by one annotator, and their
severities were carried over from that same annotator. Agreement statistics computed
against them would measure a set against itself.

Two things must happen before they replace `expected/*.json`:

1. A second qualified legal reviewer annotates the same contracts blind, from the pack.
2. Every disagreement is adjudicated in writing, with zero left unresolved.

## The DPA split is deliberately unresolved

`dpa.breach_and_dpia_assistance` covered two distinct Art. 28(3)(f) GDPR duties:
notification of a personal data breach, and assistance with data protection impact
assessments. A review that reported them separately was scored as having missed a
clause, which was a defect in the gold set rather than in the review.

They are now `dpa.breach_notification` and `dpa.dpia_assistance`. Their severities are
carried over from the composite clause and marked as **not separately calibrated**.
Assigning them independently is an adjudication decision, not a migration decision.

## Blindness is procedural, not technical

`pack/MANIFEST.json` lists every file it contains with a hash, and names every category
withheld: the current gold, the candidate obligations, the aliases, the severity
rationales, all model output, all scores, and the maintainer's own annotation guideline,
which discusses scoring and would leak both the metric surface and the first annotator's
approach. The pack ships a purpose-written annotator guideline instead.

`tests/test_annotation_pack.py` asserts that none of that content appears inside the
pack directory.

**That is a narrower property than blindness.** This repository is public, and
`annotations/pack/` sits one directory from `annotations/drafts/` and `expected/`. The
synthetic contracts are public too, so a reviewer who searches for a distinctive clause
reaches the repository and from there the answer set. Nothing prevents it.

`make annotation-bundle` exports a standalone archive that avoids handing over a map:
the withheld list names categories rather than the paths that hold them, and the
guideline asks the reviewer not to search rather than telling them where not to look.
The repository copy keeps the path-level detail, because there it is an audit record.

What the export cannot hide is that schema identifiers in the templates carry the
project name, and the contracts are public. **Blindness therefore rests on the
reviewer's undertaking, not on access control, and every agreement statistic computed
from this annotation carries that limitation.** Anyone asking how blindness was enforced
should be told exactly this.

Removing the limitation would mean moving `expected/` and `annotations/drafts/` out of
the public repository, or issuing the pack from a separate private one, until
adjudication completes.

## Why policy v3 is inert

The evidence-bound scorer and policy v3 are implemented and tested, but
`evaluate_v3` raises `GoldNotAdjudicated` for any gold set whose
`annotation_status` is not `frozen` and whose `adjudication_status` is not
`complete`. Every committed candidate set fails that check, and a test asserts it on
the real files.

The refusal is the feature. Policy v3 is stricter than v2: it requires perfect
obligation precision and recall, perfect risk precision, recall and severity, and
every finding bound to exactly one obligation by its own cited evidence. Running that
against candidates derived by one annotator from that annotator's own earlier gold
would produce a stricter-looking instrument whose stricter judgment is still one
unreviewed opinion.

## What the DPA split currently demonstrates

`dpa.breach_notification` and `dpa.dpia_assistance` were split from one v1 clause and
share its span. A citation into that passage therefore overlaps both equally, and the
scorer reports `evidence_ambiguous` rather than crediting whichever sorts first.

That is correct: until adjudication sets their boundaries, evidence genuinely cannot
tell the two duties apart. The scorer refusing to guess is what keeps the candidate
set from reading as more settled than it is.

## When Annotator B returns

The processing side is built and tested; only the annotation itself is missing.

1. Place their files at `annotations/returned/annotator-b/<case>.annotator-b.v2.json`.
2. Run `uv run python scripts/compare_annotations.py annotations/returned/annotator-b`.

That validates every returned offset against the contract, freezes the return's hash
before comparing so the comparison cannot later be re-run against an edited file, and
writes a ledger per case to `annotations/ledgers/`.

Obligations are matched by span overlap rather than by identifier, because two people
working blind will not choose the same names and matching on names would manufacture
disagreement where there is none.

The statistics are descriptive. Obligation agreement, exact risk agreement, severity
agreement and linearly weighted Cohen's kappa summarise how two readings differ; they
do not establish that either is correct. Kappa reports `not defined for this sample`
rather than a flattering number when the sample is degenerate, which it will be if
either annotator used one severity throughout.

The ledger is the output that matters. Each row is a decision someone has to make in
writing, and the gold set cannot be frozen while any row is unadjudicated.
