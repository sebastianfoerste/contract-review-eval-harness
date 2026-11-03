# Annotation guideline for the synthetic ICT agreement

You are asked to record, for each document variant and each playbook, the issues a
careful reviewer acting for the Customer must raise under that playbook. Your answers
become the reference against which automated candidate findings are later matched.
Nothing you write is legal advice; the agreement, the parties and the scenario are
fictional.

## What you receive

| Folder | Content |
| --- | --- |
| `documents/` | Each variant as a Word file and as a numbered paragraph listing |
| `playbooks/` | The two playbooks with their stable entry IDs |
| `sources/` | The source register and a snapshot of the cited provision text |
| `templates/` | One empty annotation file per variant and playbook |
| `instructions.md` | The business instructions given with every review |

`MANIFEST.json` lists every file with its hash and names what was withheld. Do not
search the public repository or the web for this agreement. If you have already
seen automated findings for it, say so in `sawModelOutput`.

## Unit of annotation

One expected issue is one playbook entry applied to one place.

- A paragraph deals with the subject of the entry but falls short of it: write the
  entry ID and the number of that paragraph. The listing shows paragraphs as `P0`,
  `P1` and so on; in the template enter the number only, as you would enter `41`
  for a paragraph `P41`. Numbering starts at 0 with the title line.
- No paragraph deals with the subject of the entry at all: write the entry ID with
  `missingClause: true` and no paragraph.
- The entry is satisfied: write nothing.
- Two different paragraphs each fall short of the same entry: write two issues.
- One paragraph falls short of two entries: write two issues.

Tie-break: the subject of an entry is the specific right or obligation the entry
asks for, not the wider topic it belongs to. Locate an issue at a paragraph whenever
some paragraph deals with that subject, however thinly. Use `missingClause` only
when none does. Where several paragraphs touch the subject, name the one that comes
closest, and write a second issue only where another paragraph separately falls
short. One entry is never both missing and located in the same file; the template
check refuses that.

An invented illustration, on subjects that are in neither playbook and in no
paragraph of this agreement. An entry asks for the provider to hold insurance of a
stated minimum amount. A paragraph in which the provider's parent company guarantees
performance deals with a guarantee, not with insurance: record a missing clause. A
paragraph that requires insurance and states no amount deals with the subject and
falls short: record the issue at that paragraph.

Apply only the playbook named in the template. A commercial preference is not a
statutory requirement and the other way round; do not borrow entries across
playbooks. Do not add entries, severities or proposed amendments. The format has no
severity field, and amendments are assessed separately by a lawyer.

Annotate every variant on its own. Read every paragraph of each variant before you
fill its template; the variants differ, and copying one answer set to another
variant defeats the exercise.

## Matching rule, declared in advance

An automated finding is later counted as matching your expected issue only when all
of the following hold:

1. Its playbook entry ID, its paragraph and its missing-clause flag are identical to
   yours.
2. The entry exists in the playbook and the finding files it under the entry's
   category.
3. A finding on an existing paragraph quotes a passage that appears verbatim in
   that paragraph and proposes no separate insertion point. The passage has at
   least 20 characters once every run of spaces, tabs and line breaks is read as
   one space and such characters at either end are dropped, or it is the whole
   paragraph where the paragraph is shorter.
4. A missing-clause finding carries no quotation and names no paragraph as its
   place. If it proposes where a new clause should go, that place is a paragraph of
   the document.

A finding that is repeated matches once, and each repetition counts against the
candidate. Every finding that does not match counts against it too. An attempt that
returns nothing has found none of your issues. The explanation and the amendment
text of a finding are not matched at all; they go to lawyer review. The result is a
matching proxy, not a judgment of legal correctness.

The candidate is not told the tie-break above. A finding that raises the right
entry at another place, or as missing where you located it, does not match. A
second figure is therefore reported beside the first: whether each entry you
expected was raised at all by a finding that is well formed under points 2 to 4,
whatever the place.

## Rationale, confidence and doubts

Give each issue one or two sentences saying why the entry is not met. For a
statutory entry, name the provision you rely on; the snapshot under `sources/` is a
convenience copy, and the official text is authoritative. Mark your confidence
`HIGH`, `MEDIUM` or `LOW`. A low-confidence issue stays in your file and is shown
to the person who resolves differences. If it enters the reference, every later
report counts it as a low-confidence issue.

Use `uncertainties` for anything the template cannot hold: an entry you consider
wrongly framed, a paragraph you read two ways, an assumption you had to make. That
text is read before differences are resolved.

## Filling a template

Open the template for the variant and playbook you are working on. Its first eight
fields identify the material and are already filled in; leave them exactly as they
are. Fill in the remaining fields. The fragment below shows their shape with an
invented entry and an invented paragraph number that exist in no playbook and no
document of this pack. It is not an answer, and a file containing it would be
rejected.

```json
{
  "annotator": "The label agreed with the maintainer",
  "annotatedOn": "2026-10-20",
  "sawModelOutput": false,
  "issues": [
    {
      "playbookReference": "EXAMPLE-LOCATED",
      "paragraph": 97,
      "missingClause": false,
      "rationale": "One or two sentences on why this paragraph falls short of the entry.",
      "confidence": "HIGH"
    },
    {
      "playbookReference": "EXAMPLE-ABSENT",
      "paragraph": null,
      "missingClause": true,
      "rationale": "One or two sentences on why no paragraph deals with the entry's subject.",
      "confidence": "MEDIUM"
    }
  ],
  "uncertainties": ""
}
```

If you find nothing to raise for a variant and playbook, leave `issues` empty and
still fill in your label, the date and `sawModelOutput`.

## What happens to your file

A second reviewer annotates the same material separately. Your file is never
edited. Where the two files differ, each difference is decided in writing with
reasons, and the record of those decisions is kept. Only then is a reference called
independently reviewed. The reference carries hashes, the letters A and B and a
pointer to a dated note that the maintainer keeps outside the repository.

Your returned file is kept with the experiment it supports and may be published
with it, including what you wrote in `annotator`. Write the label agreed with the
maintainer there, not your name.

## Return

Send back the six filled templates and the time you spent. Keep a copy.
