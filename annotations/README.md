# Annotations

## Status

The authoritative gold sets remain `expected/*.json` under schema v1. Nothing in this
directory decides anything yet.

| Artifact | Status |
| --- | --- |
| `drafts/*.candidate.v2.json` | Candidate. Single annotator, mechanically derived offsets. |
| `pack/` | Built, not sent. Transmission requires explicit approval. |
| Second annotation | **Not started.** Hard external dependency. |
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

## The pack is blind by construction

`pack/MANIFEST.json` lists every file it contains with a hash, and names every category
withheld: the current gold, the candidate obligations, the aliases, the severity
rationales, all model output, all scores, and the maintainer's own annotation guideline,
which discusses scoring and would leak both the metric surface and the first annotator's
approach. The pack ships a purpose-written annotator guideline instead.

`tests/test_annotation_pack.py` asserts the exclusion holds rather than trusting it.

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
