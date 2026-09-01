# Annotation guideline

How to author a gold answer set for this harness, so that a set written six months
from now is comparable with the ones already here.

The gold sets carry the value in this repository. The scoring code is ordinary; the
judgment about which clauses matter and how badly a defect bites is not. This document
exists so that judgment stays consistent rather than drifting with whoever writes the
next case.

## What a case is

A case is four files and one entry:

```text
data/<case>_sample.md        the synthetic agreement
expected/<case>.json         the gold answer set
fixtures/<case>_stub.json    deterministic offline adapter output
robustness/campaign.v1.json  scenarios naming the case
src/contract_eval/cases.py   add <case> to ALL_CASES
```

## Writing the synthetic agreement

Fabricate it. Never adapt a real agreement, a client precedent, or a template whose
provenance you cannot state. The synthetic-data boundary is the reason this repository
can be public at all.

Plant defects deliberately and record why each one is a defect while you write it —
that reasoning becomes the gold answer, and reconstructing it afterwards invites
rationalisation. Aim for a spread:

- one or two defects any competent reviewer catches (an obviously excessive term, an
  indefinite retention right);
- one or two that require knowing the instrument (an authorisation right waived, an
  audit right narrowed to a certificate, a transfer clause with no legal mechanism);
- at least one clause that is merely unusual rather than wrong, so the set can
  distinguish a finding from a false positive.

Write clauses that can be quoted verbatim. Citation grounding matches against the
document text, so a clause phrased in a way no reviewer would quote cannot be tested.

## Choosing clause types

Clause types are `snake_case` and name the obligation, not the section heading. Where a
regulation enumerates requirements, follow its enumeration exactly — the DPA case uses
one clause type per Art. 28(3) requirement, lit. a through h, in the regulation's own
order. Where there is no enumeration, use the term a practitioner would use in a
playbook, not the drafter's chosen heading.

A clause type belongs in `clause_types` when a reviewer would be wrong to omit it from a
review. Do not add a type for material that is present but unremarkable.

## Assigning risk severities

Severity answers one question: **what happens if this goes unnoticed and the agreement
is signed?**

- `high` — the clause defeats a mandatory requirement, removes a right the counterparty
  cannot practically recover, or exposes the client to an uncapped or unquantified
  liability. A regulator, court, or auditor would treat it as a defect, not a
  negotiating position.
- `medium` — the clause is materially worse than the market position and should be
  negotiated, but a reviewer who accepted it with reasons would not be negligent.
- `low` — the clause is unusual or slightly off-market and worth a note.

Calibrate against the instrument, not against how unusual the drafting looks. A
familiar-looking clause that defeats a mandatory requirement is `high`. Unusual drafting
that changes no substantive right is not a finding at all.

Record the severity you would defend in writing to the client. If two annotators would
plausibly disagree, the case is a poor benchmark item: either sharpen the planted defect
or leave the clause unflagged.

Every risk flag must carry exactly one `severity_rationale` entry, and it must contain
real text. This is enforced, not conventional: a flag with no written justification, an
empty rationale map, or a blank string all fail validation. A severity nobody wrote a
reason for is an assertion, and assertions are what this repository exists to replace.

## Writing the stub fixture

The stub is not a model. It is a fixture that decides what the scorecard demonstrates,
so choose its errors deliberately.

Make it fail in the way real review fails: strong clause coverage with weak severity
judgment. A stub that finds every clause and still misses two material defects
demonstrates the thesis of this repository. A stub that misses clauses only demonstrates
that recall is computable.

Every stub carries exactly one fabricated citation. The release certificate rejects any
case with an unsupported citation, so this keeps the baseline decision at `REJECT` and
the gate honest.

Do not tune a fixture to clear a threshold. If a case cannot pass its own gate, either
the planted defects are unreasonable or the thresholds are wrong — fix whichever is
actually at fault and say which in the commit message. Moving a threshold to make a
number look better is the failure mode this repository exists to expose.

## Declaring clause aliases

Adapters name clauses in their own vocabulary. A review that writes `no_licence` for
`no_license`, `sub_processors` for `subprocessors`, or `audits_and_inspections` for
`audit_rights` is a correct review with different labels, and scoring it as a missed
clause measures vocabulary rather than legal judgment.

`clause_aliases` in the gold set maps a synonym onto the gold set's own name for **the
same clause of the same document**. Add an alias when you meet a label that names the
clause you meant just as accurately as yours does.

Never add one to make a wrong answer pass. An alias that maps onto a different clause
lets a review about section 8 score as a review about section 4, which is the exact
failure this harness exists to catch, reintroduced inside the benchmark.

Validation is structural only. The tests assert that every alias target is a declared
clause type and that no alias shadows a canonical name. They cannot tell whether an
alias is a genuine synonym: mapping `termination` onto `audit_rights` passes every
automated check. Aliases are therefore manually reviewed, and the written defence of
each one is the actual control.

Two aliases collapsing onto the same clause are reported as duplicates, and a duplicate
carrying a different severity is reported as a conflict. A review that flags one clause
both high and low contradicts itself and is not treated as agreeing with the gold set.

### Known limitation

Aliases are added after observing what a model returned, which fits the benchmark to
whatever vocabulary the last run happened to use. Runs on 2026-08-28 and 2026-09-01
produced different labels for the same clauses, so a map built from the first did not
transfer to the second.

A one-to-one map also cannot express a granularity difference. On the DPA case a model
returned `data_breach_notification` and `dpia_assistance` as two clauses where the gold
set carries a single `breach_and_dpia_assistance`; no set of synonyms fixes that.

Label-based clause scores are therefore a lower bound on coverage, and should be read
with `span_coverage` beside them.

## Writing clause anchors

Every clause type carries a `clause_anchors` entry: a verbatim phrase from the contract
that locates the clause. Anchors are how coverage is measured without reference to
vocabulary, so they carry more weight than aliases do.

Choose a phrase that is distinctive to the clause and that a reviewer would plausibly
quote. It must occur exactly once in the document; `make anchor-check` fails the build
otherwise, because an anchor matching twice credits coverage to whichever region comes
first.

Each clause owns the region from its own anchor to the next anchor in document order.
Anchor near the start of the clause, so its region covers the clause body rather than
beginning halfway through it.

## Adding adversarial scenarios

Each scenario is a minimal pair: the smallest edit that changes the legal answer, plus a
statement of how the review should change. Anchors must occur exactly once in the source,
and the harness enforces that.

Every case needs at least one `semantic_control` — an edit that changes formatting and
nothing else. Without a control there is no way to separate a genuine finding from a
model that reacts to any change at all. The campaign validator rejects a case that has
no control.

Cover, per case:

- a removed or inverted obligation;
- a duration or threshold changed beyond what the instrument allows;
- a referenced schedule that does not exist, expecting an **abstention** rather than a
  confident answer;
- an instruction injected into the contract text, expecting the review to ignore it;
- the semantic control.

## The standing rule

The gold set is the benchmark. When a model disagrees with it, the model is wrong by
definition — so the set must be defensible on its own terms, in writing, before any
score computed against it is published. Any published comparison names the model, the
date and the harness version.
