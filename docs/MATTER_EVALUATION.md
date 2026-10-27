# Matter evaluation

The three cases under `data/` each test one document. A matter tests what a lawyer is
instructed to do: read several documents for one client, find where they contradict
each other, say what to do about each term, and say what cannot be answered yet.

This document covers the method, how answers are written, and what may be claimed at
each stage. The first matter is in [`matters/northwind-saas/`](../matters/northwind-saas/).

## What a matter consists of

| Part | Where | Purpose |
|---|---|---|
| Manifest | `matters/<id>/matter.json` | Documents with their kind, hash and round; rounds; conditions |
| Documents | paths named in the manifest | The file a lawyer would receive. Contracts under `data/` are referenced, never copied |
| Rounds | `rounds` in the manifest | The matter at successive points in time. Rounds accumulate documents |
| Conditions | `conditions` in the manifest | Which document kinds a system may see, and with which prompt |
| Answers | `matters/<id>/expected/<round>.json` | The expected issues for that round |
| Stub outputs | `matters/<id>/fixtures/<round>.<condition>.json` | Deterministic output for the offline path |
| Reviewer sessions | `matters/<id>/reviews/*.json` | What reviewing lawyers did with an output |

Every document hash is checked on load. An edited document is refused until its hash
is recorded again, because every answer is a position in specific text.

The matter path runs from a repository checkout. The wheel ships the three cases but
not `matters/`, and every matter document, the contracts under `data/` included, is
read relative to `--root`, which defaults to the working directory. Run the commands
from the repository root. They are maintainer commands: `contract-eval dev --help`
lists them, and each also runs without the `dev` prefix, as in the examples below.

## Three tasks

An expected issue belongs to one task.

- **Conflict.** Two or more documents that cannot both be performed or both be true.
  Evidence must sit in at least two documents. Tension inside one document is a
  position issue.
- **Position.** A term on which the client must take a stance. The answer records the
  expected action: `accept`, `negotiate`, `reject` or `escalate`. Where the client has
  a playbook, the playbook defines those four words and the answer names the rule.
- **Escalation.** A question that cannot be answered from the file as it stands. The
  evidence is the passage that makes the gap visible, for example a reference to an
  annex that was not provided.

A conflict carries no action. Where a conflict also calls for a stance, that stance is
a separate position issue. Keeping them apart lets a review earn credit for seeing the
contradiction without knowing the client's rule, which is the difference the conditions
are meant to show.

## Conditions

A condition is a list of document kinds. The first matter defines three:

| Condition | Sees |
|---|---|
| `baseline` | Contracts and the counterparty's written response |
| `sources` | Adds the negotiation record and the security questionnaire |
| `matter` | Adds the client's instructions and playbook |

All three are scored against the same answers. An issue is answerable under a
condition when some finding could earn credit on it from the documents that condition
sees: a position or an escalation needs one of its passages visible, and a conflict
needs what `conflict_credit` needs, which under the strict rule is every side. The
scorecard prints that count as the condition's ceiling. A low baseline score is
therefore split into two parts: what the baseline could not have known, and what it
could have found and missed.

The ceiling depends on where the answers anchor an issue. A gap that is visible in a
contract and is anchored only in the client's memo becomes unanswerable for the
baseline by the author's choice of quote, and the comparison then favours the matter
condition for a reason that has nothing to do with the system. Where a gap or a term
is visible in a document every condition sees, anchor it there.

## How a review is scored

Scoring follows the evidence-bound path of the single-contract cases. Labels and
summaries earn nothing.

1. Each citation names a document and quotes it. The quote is located in that
   document as whole words, ignoring case, punctuation and line breaks. It is
   `grounded` if it occurs there once, `misattributed` if it occurs only in a
   different document, `ambiguous` if it occurs more than once, `unsupported` if it
   occurs nowhere, and `not_visible` if the document was not shown.
2. A citation points at an answer's passage when it overlaps it and at least a quarter
   of the quotation lies inside it (`MIN_QUOTE_FOCUS`). Quoting a whole document is
   grounded and points at nothing.
3. A finding binds to the one expected issue of its task whose passages it points at
   most. If any citation it relies on is not grounded, it binds to nothing. If two
   issues tie, it binds to neither.
4. A bound position or escalation earns full credit. A conflict finding earns what
   `conflict_credit` in `src/contract_eval/matter_scorer.py` awards. The rule in force
   is strict: every document of the conflict must be quoted, or the finding earns
   nothing and is reported as one-sided.

Three further rules keep a correct review from being marked down for how it is filed.

- A position with the action `escalate` and an escalation are the same act. Each may
  bind to an expected issue of the other kind when it points at none of its own.
- Every credited finding on a position counts toward its action. A review that says
  both `reject` and `accept` on one term is wrong on the action whatever the order,
  and is listed under contradictory actions.
- A later round's answers list what is new. A finding that points at an earlier
  round's issue better than at any current one is listed as restated and left out of
  precision. Whether the earlier point still holds is scored only if the later
  round's answers restate it.

| Measure | Meaning |
|---|---|
| Issue recall | Credit earned over expected issues |
| Material-issue recall | The same, over issues of high materiality |
| Finding precision | Distinct issues found over findings made |
| Escalation recall and precision | Gaps surfaced, and questions asked that the file already answers |
| Action accuracy | Share of found positions with the expected action |
| False reassurance | Material positions the review said to accept and the answers say not to |
| Citation grounding | Grounded citations over all citations, with misattributed, unsupported and hidden-document citations counted separately, and citations no finding relies on counted in the open |
| Reviewer usefulness | Mean rating from recorded reviewer sessions, or "not measured" |

## Writing the answers

The answers are written by the reviewing lawyer. The harness does not generate them,
and the repository does not ship machine-drafted answers under a human's name. Until
they exist, a round has `annotation_status: "pending"` and nothing is scored.

For each issue, write the fields below and leave `start` and `end` out.

```json
{
  "issue_id": "r1.short_name",
  "task": "conflict",
  "split": "dev",
  "title": "One line",
  "description": "What is wrong, in one or two sentences.",
  "materiality": "high",
  "evidence": [
    {"document_id": "saas", "quote": "verbatim text, occurring once in that document"},
    {"document_id": "dpa", "quote": "verbatim text from the other side"}
  ],
  "rationale": "Why this is an issue and why it has this materiality.",
  "source_category": "legal_judgment"
}
```

Then run:

```bash
uv run python scripts/matter_sync.py --write
uv run python -m contract_eval matter-check
```

The first command locates every quote and records its offsets. It fails if a quote
does not occur exactly once in its document. The second validates the result.

Rules the validator enforces:

- A position needs `expected_action`. An escalation has `expected_action: "escalate"`.
- `source_category` is one of `law`, `regulatory_guidance`, `market_practice`,
  `client_playbook` or `legal_judgment`. The first, second and fourth require a
  `source_reference`. A `playbook_rule` must exist in a playbook document of the round.
- Two issues of one task may not have identical evidence, and the evidence of one may
  not be contained in the other's. Give each issue a passage of its own.
- A passage must be unique in its document once case and punctuation are ignored.
- Set `status.annotation_status` to `draft` or `candidate`, and `annotator_id` to the
  author's name, when the first issue is added.

Write the answers before reading any model output for the matter. Answers written
after looking at what a system found inherit its blind spots.

## Development and evaluation issues

Each issue is assigned to `dev` or `eval` when it is written. Prompts, playbook wording
and context selection are tuned on `dev` only.

```bash
uv run python -m contract_eval matter-evaluate --split dev --log experiments/northwind-saas/log.jsonl
```

Runs on the committed fixtures are logged only on request. Live runs and runs that
score an output file are always logged, to `experiments/<matter>/log.jsonl`.

Every logged run records a configuration id: a hash of the prompt as sent, which
contains the documents shown, with the model and the reasoning effort. A live run and
the later scoring of its capture share one id. An output file that records no prompt
is identified by its content. Every run also records the hash of the answers.

The scorecard prints **Not held out** in two cases: the evaluation split of the round
was scored earlier under a different configuration of the same condition, or the
answers changed after that split had been scored under any condition. The run is not
blocked. It is labelled, because a number chosen after seeing evaluation results does
not describe unseen issues. A development scorecard contains no evaluation issue ids.

The guard judges one round and one condition id at a time. Registering a tuned prompt
under a new condition id, or tuning on round one before scoring round two, is not
detected. Both are changes to the manifest and visible in version control.

Two limits apply to this split. Development and evaluation issues come from the same
documents, so the evaluation issues are unseen issues in a seen matter. A claim about
unseen matters needs a second matter. Round two contains facts that round one does
not, which makes it the closer test of adaptation to change.

## Live runs

The default path is offline. A live run is opt-in:

```bash
uv sync --extra live
uv run python -m contract_eval matter-evaluate --round round1 --live
```

`--live` is the alias for `--adapter anthropic`, as for the cases. The OpenAI-compatible
and command adapters return a case review and have no matter counterpart. Another
tool's matter review is scored from a file with `--review`, as shown below.

Every attempt leaves a file in `captures/matters/<id>/`: the raw response when one
came back, or a record of the failure when the call raised, so failed attempts can be
counted. A capture is scored only as the matter, round and condition it was made for,
and can be scored later without calling the model again:

```bash
uv run python -m contract_eval matter-evaluate --round round1 \
  --review matter=captures/matters/northwind-saas/<file>.json
```

This allows outputs to be captured before the answers are written and scored
afterwards, which keeps the answers independent of the outputs.

## Reviewer sessions

A score against the answers shows what a review found. It does not show whether a
lawyer would use it. That is recorded by a person, per finding.

```bash
uv run python -m contract_eval matter-review-template --round round1 \
  --review captures/matters/northwind-saas/<file>.json \
  --out matters/northwind-saas/session-template-round1.json
```

The template names the output by hash and does not name the condition. The reviewer
records, for each finding, `accepted`, `corrected` or `rejected`, a usefulness score
and, unless accepted, a reason. They also record review time, the time until the draft
was reviewable, and any material issue the output missed.

| Score | Meaning |
|---:|---|
| 4 | Usable as written. I would send it on with my name under it. |
| 3 | Useful after correction. The point is right; wording, severity or action needed fixing. |
| 2 | Not useful. Correct or harmless, but it told me nothing I needed. |
| 1 | Misleading. Wrong in a way that would have cost time or caused harm if relied on. |

A completed session goes in `matters/<id>/reviews/`. Every file there is validated as
a completed session, so a blank template stays in the matter directory beside it.
Reviewers are recorded under a pseudonym such as `R01`. Each session declares an
`evidence_class`. Only sessions by practising lawyers other than the author count
toward the usefulness figure; the author's own review and worked examples are counted
as excluded.

## What may be claimed

| Stage reached | Claim it supports |
|---|---|
| Matter documents and scorer, answers pending | A matter-level evaluation design exists and its scorer is tested on a toy matter |
| Answers written by one lawyer | A single-annotator candidate answer set. Scores are relative to one person's judgment |
| Live outputs scored on `dev` and `eval` under each condition | A measured difference between conditions on one synthetic matter, for a named model, date and harness version |
| Reviewer sessions by practising lawyers | A user pilot on synthetic documents, with its sample size stated |
| Blind second annotation and written adjudication | A validated answer set for this matter |
| Adoption inside an organisation, with scope and results recorded | An enterprise implementation. Nothing in this repository supports that claim |

## Limitations

- One matter, three contract types, one client side.
- The contracts are the certified synthetic cases. The six further matter documents
  were drafted with AI assistance to create tensions with them and with each other,
  and need the author's review before the answers are written.
- Evidence binding measures where a review quoted. A finding that quotes the right
  passages and reasons wrongly about them earns credit for detection. Action accuracy
  and reviewer sessions are the checks on reasoning.
- The matter path is not part of the release certificate, the robustness campaign, the
  leaderboard, the GitHub Action or the web export, and the wheel does not ship
  `matters/`.
