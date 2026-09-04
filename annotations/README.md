# Annotations

## Status

The authoritative gold sets remain `expected/*.json` under schema v1. Nothing in this
directory decides anything yet.

| Artifact | Status |
| --- | --- |
| `drafts/*.candidate.v2.json` | Candidate. Single annotator, mechanically derived offsets. |
| `pack/` | Built, not sent. Transmission requires explicit approval. |
| Second annotation | Karsten Schmidt, agreed and named. Pack not yet sent. |
| Adjudication tooling | Implemented and tested. Waiting on a return to process. |
| Evidence-bound scoring | Implemented. Inactive: policy v3 refuses candidate gold. |
| Policy v3 / certificate v4 | Defined. Cannot certify until gold is frozen and adjudicated. |
| Campaign v2 | Generated as a candidate. Regenerate after adjudication. |
| v2 evaluation path | Wired end to end. Runs today; certifies nothing. |
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

## Who wrote what

| Slot | Annotator | Role |
| --- | --- | --- |
| `annotator-a` | Sebastian Förste | Author of the v1 gold sets and the candidate v2 obligations. |
| `annotator-b` | Karsten Schmidt | Independent second annotator, working blind from the pack. |

Both are named with their agreement. A public repository is a permanent, searchable
record, so a reviewer is named only once they have said yes.

Identity and role stay separate. `src/contract_eval/annotators.py` is the single place
either name appears; directory and file names key off the stable slot instead, so
adding or replacing a reviewer never renames artifacts or breaks the comparison script.

Naming the annotators is not a substitute for blindness. Karsten works from the bundle
alone, and the limitation recorded below still applies to any statistic drawn from the
comparison.

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

## The campaign is generated, not written

`robustness/campaign.v2.candidate.json` holds 75 scenarios covering all 33 candidate
obligations: a removal and an inversion for each, plus a missing-schedule, an
instruction-injection and a semantic control per case.

They are generated by `make campaign-v2` rather than hand-authored, because every
scenario keys to an obligation id and to raw offsets, and adjudication can move both.
Regenerating after the gold is frozen is one command; rewriting seventy-five
hand-written scenarios would not be.

Mutations carry the slice they expect to replace and the hash of the source they were
built against. If either moves, `make campaign-v2-check` fails before any adapter runs,
because a scenario applied to text it was not written for measures something nobody
designed.

### The split duties surface here too

Generating the campaign failed on the first attempt: removing `dpa.breach_notification`
necessarily damages `dpa.dpia_assistance`, because they share a span. The boundary check
refused rather than letting one scenario quietly rewrite a neighbouring duty.

The generator now declares co-located siblings as affected, which records that no
scenario can isolate one of those duties from the other. That is the third place the
unresolved split has appeared, after `evidence_ambiguous` in binding and the shared-span
`adjudication_note` in the gold. It is a boundary question only a human can settle.
