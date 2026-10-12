# My Counsel native candidate track

This is a separate synthetic engineering track. It does not enter `ALL_CASES`,
the three-case reference freeze, or a release certificate. It evaluates the
actual My Counsel candidate prompt, schema and validators on one synthetic
agreement. Everything recorded so far is a hand-authored replay, including a
duplicate and an unknown playbook reference. No model run, no independent
annotation and no legal-quality improvement is claimed.

## What is here

| Path | Role |
| --- | --- |
| `manifest.json` | Frozen synthetic corpus: three document variants, two playbooks and the business instructions, pinned by hash |
| `ict-*.docx`, `ict-*.md` | The English ICT services agreement under German law: base, changed, injection |
| `commercial.json`, `dora.json` | Structured playbooks (`mycounsel.playbook.v1`), six entries each |
| `build_fixtures.py` | Generates the documents, playbooks and manifest deterministically |
| `sources.json`, `sources/` | Source register and snapshot of the cited provision text |
| `annotation/GUIDELINE.md` | Annotation instructions and the matching rule, as sent to annotators |
| `annotation/COVER-NOTE-DRAFT.md` | Draft cover note for the annotator; not part of the pack and not sent |
| `annotation-pack/` | Built pack: documents, playbooks, sources, six empty templates, manifest |
| `experiments/replay-dry-run/` | Zero-cost worked example of a preregistered experiment and its report |
| `spend-ledger.json` | Cumulative EUR 100 cap for paid attempts, with one verified price row and no entries |
| `replay-run.json`, `replay-score.json` | The hand-authored replay and its score |

The code is in `src/contract_eval/`: `candidates.py` scores one recording,
`candidate_annotation.py` builds the pack and compiles one annotation,
`candidate_adjudication.py` resolves two annotations, `candidate_experiment.py`
holds preregistered experiments, and `candidate_budget.py` is the ledger.

## Reproduce the replay

With the private ZuRecht checkout beside this repository:

```sh
python candidates/mycounsel/build_fixtures.py
cd ../zurecht
node --import tsx scripts/record-contract-candidates.ts base commercial /tmp/candidate-run.json
cd ../contract-review-eval-harness
uv run python -m contract_eval.candidates /tmp/candidate-run.json --document candidates/mycounsel/ict-base.docx
make candidate-check
```

The recorder refuses to overwrite an earlier attempt. Other arguments are
`changed` or `injection` and `dora`. Regenerating a recording changes its start
time, elapsed time and source-revision metadata. Fixture generation is
deterministic. The exact original bytes, paragraph anchors, playbook text,
business instructions, prompt version, code revision and dirty-tree state are
retained. Errors and refusals remain attempts. Provider error text is excluded.

## What one recording is scored on

- **Quotation validity** mirrors the application: any non-empty passage that
  occurs verbatim in the anchored paragraph, with no separate insertion anchor.
  A valid quotation shorter than 20 characters that is not the whole paragraph
  is counted as trivial and cannot match an expected issue.
- **Playbook validity** means the entry ID exists and the finding carries that
  entry's category.
- **Missing-clause shape** means no quotation and no clause anchor; an insertion
  anchor, if given, must exist.
- **Duplicates** are findings that repeat a playbook entry, anchor and
  missing-clause flag.
- **All findings valid** recomputes what the application decides: it passes an
  output on only when every finding in it is valid. The recorder's own accepted
  or rejected flag is kept beside it and never used in a figure.
- **Issue matching** needs a reference bound to the same document and playbook.
  A finding matches when entry, anchor and missing-clause flag are identical and
  the finding is matchable under the three points above. A repeated finding
  matches once; every finding that does not match is a false positive. An
  attempt without output finds nothing, so every expected issue is a false
  negative. An entry-level companion figure asks only whether an entry was
  raised anywhere.

Matching cannot establish a correct legal explanation or amendment. Severity
accuracy and complete clause coverage are unavailable because the native output
has neither field. Token usage is recorded when the recorder supplies it and
otherwise carries the reason it is absent. Cost is never part of a recording.

## Source register

`sources.json` lists the primary source the DORA playbook relies on, with the
URL, fetch time, snapshot path and SHA-256 of the provision text. The code holds
the register to its claims: the snapshot must hash to the registered value, every
entry it cites must exist in a playbook with a pinpoint, and every statutory
playbook entry must be covered. A register that lags the playbook stops the pack
from building.

The snapshot file under `sources/` holds the Official Journal text of Article 30
of Regulation (EU) 2022/2554. On 11 October 2026 it was compared with a second
download from the Publications Office repository: identical, no amending act, no
English corrigendum and no English consolidated version. The EUR-Lex website's own
display was not read, because it answered automated requests with a browser
check. The six playbook sentences were then aligned with the wording of
Article 30(2)(b), (d), (f) and 30(3)(a), (e), (f).

The register's status is `SOURCE_CHECKED_NOT_LAWYER_REVIEWED`. Open for the
lawyer review, among others: whether a rate card satisfies "a cost that is
determined ex-ante" in Article 30(2)(f), and how the unrestricted audit rights in
Article 30(3)(e)(i) sit with the alternative assurance levels in point (ii). The
register's `notCovered` list names what a playbook drawn from six points of
Article 30 leaves out, including the two delegated regulations on subcontracting
and on the policy on contractual arrangements.

## Blind annotation

`make candidate-pack` builds `annotation-pack/` from the corpus: numbered
paragraph listings per variant, the playbooks, the source register, the business
instructions, one empty template per variant and playbook, and a manifest that
hashes every file and names what was withheld. `make candidate-pack-check`
recomputes those hashes and rebuilds the pack in a scratch directory, so a pack
that predates a change to the guideline, a playbook or the register fails.
`make candidate-bundle` zips a pack that passes the same check and prints the
archive's SHA-256.

A template carries eight binding fields the annotator leaves unchanged: schema,
variant, playbook and the hashes of the document, the playbook, the corpus
manifest, the guideline and the source register. The annotator fills in a name
or agreed label, the date, whether model output was seen, and the issues by
playbook ID and paragraph number.

The tests assert that the pack contains no finding, score field or construction
note of the withheld files, and that the guideline's worked example uses an entry
and a paragraph that exist nowhere in the corpus. Blindness beyond that is
procedural: this repository is public, and the guideline asks the reviewer not
to search.

One filled annotation can be checked and compiled:

```sh
uv run python -m contract_eval.candidate_annotation check returned/base-commercial.annotation.json
uv run python -m contract_eval.candidate_annotation compile returned/base-commercial.annotation.json --out base-commercial.draft.json
```

`check` and `compile` refuse an unfilled template, an annotation made from a
different pack, an unknown entry, a paragraph outside the document and an entry
that is both missing and located. A single annotation always compiles to a
`DRAFT` reference. Its provenance block records the pack hashes, the number of
low-confidence issues, whether doubts were written down and whether the annotator
had seen model output.

## Two annotators and written adjudication

A reference is called `INDEPENDENTLY_REVIEWED` only after two blind annotations
of the same cell and a written decision on every difference:

```sh
uv run python -m contract_eval.candidate_adjudication compare A.json B.json --markdown ledger.md
uv run python -m contract_eval.candidate_adjudication prepare A.json B.json --out adjudication.json
uv run python -m contract_eval.candidate_adjudication resolve A.json B.json adjudication.json --out reference.json
```

`compare` lists every issue only one annotator raised, with its kind: `LOCATION`
when the other annotator raised the same entry elsewhere, `PRESENCE` when not at
all. The statistics are three counts and positive agreement; they are descriptive
and never a pass mark, and no kappa is computed. `prepare` writes a blank record
with one undecided entry per difference, bound to both annotation files by hash,
and never overwrites a file. `resolve` refuses until every entry is decided
`INCLUDE` or `EXCLUDE` with written reasons and the record names the adjudicator,
the date, which annotator is independent of the maintainer and the note that
identifies that person. The returned annotation files are never edited: any
change breaks the hashes the record binds. The reference carries hashes and the
letters A and B, not names.

Annotation files and adjudication records contain the names or labels their
authors wrote. Whether they are committed to this public repository is the
owner's decision; an experiment needs them beside the reference, see below.

## Preregistered experiments

`contract_eval.candidate_experiment` holds the design from the portfolio plan,
two playbooks by three variants by two repetitions per arm, as a file that exists
before any attempt runs:

```sh
uv run python -m contract_eval.candidate_experiment plan --out candidates/mycounsel/experiments/<id> \
  --id <id> --mode LIVE --repaired changed:DORA-LOCATIONS \
  --prompt-version <version> --code-revision <clean-commit> --model <catalog-model>
uv run python -m contract_eval.candidate_experiment add-reference <dir> --playbook dora --variant base \
  --annotation-a references/sources/dora-base.a.json --annotation-b references/sources/dora-base.b.json \
  --adjudication references/sources/dora-base.adjudication.json
uv run python -m contract_eval.candidate_experiment reserve <dir> --arm baseline --id <reservation-id> \
  --provider gemini --region eu --max-input-tokens <n> --max-output-tokens <n>
uv run python -m contract_eval.candidate_experiment register <dir>
uv run python -m contract_eval.candidate_experiment aggregate <dir> --out <dir>/report.json --markdown <dir>/report.md
uv run python -m contract_eval.candidate_experiment settle <dir> --arm baseline --id <settlement-id>
```

What each step freezes or refuses:

- `plan` writes one empty slot per arm, playbook, variant and repetition and
  never overwrites an existing experiment. The slots are exactly what the design
  implies; a slot that is removed, added or pointed elsewhere is refused.
- `add-reference` registers the reference at `references/<playbook>-<variant>.json`
  only while no attempt is registered and no budget is reserved. A reference that
  claims independent review must name its two annotations and its adjudication
  record under `references/sources/`; it is re-derived from them then and on
  every aggregation. A `DRAFT` reference needs no sources and stays labelled.
- `add-iteration` adds the one iteration arm with its written change and
  hypothesis. It must run the baseline's model and differ in prompt version or
  code revision. It is refused once files exist for that arm.
- `reserve` is for LIVE experiments only. It requires a reference for every
  cell and no attempt file for the arm, writes the worst-case hold into the
  ledger together with a hash of the arm's whole definition, and binds the
  reservation to the arm. `void` releases it while nothing was dispatched.
- `register` checks each newly recorded attempt in full and binds it by hash.
- `aggregate` refuses an attempt whose prompt version, code revision, model,
  mode, document, playbook or business instructions differ from the
  preregistration; a LIVE attempt from a dirty working tree; a registered attempt
  that changed or disappeared; an unregistered or unplanned attempt file; the same
  recording or the same provider request in two slots; and a changed corpus or
  reference. For a LIVE experiment it reads the ledger and also refuses an arm
  without a reservation, a reservation that differs from the bound one, an arm
  whose definition changed after the reservation, an attempt that started before
  the reservation or on a price older than the ledger allows, a voided
  reservation with attempts, and attempts registered after settlement.

The report gives every planned cell: planned, observed, completed, refused and
failed attempts; findings, duplicates, trivial quotations, quotation and playbook
validity with denominators; attempts in which all findings are valid beside the
recorder's own flag; identical outputs across repetitions; provider-reported
usage; and, where a reference is registered, precision and recall over all
observed attempts, the same figures after application validation, and entry-level
recall. Injection variants add how many completed attempts returned nothing and
how many findings quoted the injected paragraph. A variant declared with
`--repaired` adds how many findings still cite the repaired entry. Baseline and
iteration are compared only on identical inputs and only where both have a
completed attempt; each difference is shown with the two values behind it.

`experiments/replay-dry-run/` is the zero-cost worked example: the one
hand-authored replay registered in a twelve-slot REPLAY design. Its report shows
one observed attempt and eleven not run, no reference and no comparison.
`make candidate-experiment-check` re-aggregates every committed experiment and
fails if a report differs by a byte.

Limits. Time order and freezing are evidence from files the operator maintains,
not a signature; committing the experiment file and the ledger before dispatch is
what makes the order provable to someone else. A REPLAY experiment reserves
nothing and has no such freeze. No tooling here verifies who an annotator is.

## Spend ledger

`spend-ledger.json` is the only record of the cumulative EUR 100 cap, in cents.

```sh
make candidate-budget-status
uv run python -m contract_eval.candidate_budget price --model gemini-3.8-flash --provider gemini --region eu \
  --list-currency USD --input-minor-units-per-million <n> --output-minor-units-per-million <n> \
  --verified-on <date> --source-url <provider price page> --conversion-note "<figures, rate, rate date>"
```

- A price row is read from the provider's page on the stated date. A row older
  than `maxPriceAgeDays` refuses to reserve, and an attempt dispatched on a row
  that old is refused at aggregation. A row cannot be changed while a reservation
  made at other figures is open.
- The hold for one attempt is maximum input tokens times the input price plus
  the provider-side output ceiling times the output price, rounded up to a whole
  cent. The output ceiling includes the gateway's thinking headroom, because
  thinking is billed as output. A price converted from another list currency
  carries a 10 per cent allowance, stored with the reservation. The reservation
  is that hold times the arm's attempts times a retry multiplier.
- A settlement is an upper estimate: reported usage at the reserved price,
  rounded up once, plus the full hold for every observed attempt that reported
  no usage. Planned attempts that never ran cost nothing. The provider's invoice
  is authoritative.
- Entries are appended in time order and validated as a history. A reservation
  that would pass the cap is refused. A settlement is a fact: it is recorded even
  above its reservation, and the status then reports the overrun.
- One recording shows one provider response. A request the provider's client
  repeated internally may have been billed more than once; the retry multiplier
  is the allowance for that.

The current row prices `gemini-3.8-flash` on the Vertex AI `eu` endpoint, the
model production runs for contract analysis, at the gross list price read on
11 October 2026. With 6,000 input tokens and the gateway's output ceiling of
12,096 tokens, one attempt holds 11 cents and one arm of twelve attempts with a
retry multiplier of two holds EUR 2.64.

The ledger dispatches nothing. Dispatch is the live mode of
`scripts/record-contract-candidates.ts` in ZuRecht, which refuses to call the
model unless the arm's reservation is open in this ledger.

## Case and legal review boundary

The fictional customer is a German credit institution. The exercise assumes that
the ICT service supports a critical or important function and that the customer
is not a microenterprise. These are stipulated facts, not a perimeter
determination. The commercial playbook contains customer preferences and risk
judgments. The six DORA points are a deliberately limited selection from
Article 30; they do not constitute a complete DORA, subcontracting or outsourcing
review. Proposed wording needs lawyer assessment.

The `changed` document repairs only the data-location clause, so that it states
the regions of contracted and subcontracted services and of processing and
storage and requires advance notice of envisaged changes. The `injection`
document appends hostile reviewer instructions as source evidence. The replay
does not simulate model sensitivity to either change: observed robustness
requires retained live outputs. Public-document editor exercises belong to a
separate pilot corpus and must never be relabelled synthetic benchmark evidence.
