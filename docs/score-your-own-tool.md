# Score your own tool

`contract-eval score` grades any contract-review tool's output with the same scorer the
bundled benchmark uses. It needs no adapter, no API key and no capture envelope: one
plain JSON file per review.

## 1. Export the review

Write each review as JSON matching
[`schemas/review-output.schema.json`](../schemas/review-output.schema.json):

```json
{
  "clauses": [
    {"clause_type": "governing_law", "text": "German law governs the agreement."}
  ],
  "risk_flags": [
    {"clause_type": "limitation_of_liability", "severity": "high", "rationale": "Liability is uncapped."}
  ],
  "citations": [
    {"quote": "This Agreement shall be governed by the laws of Germany", "clause_type": "governing_law"}
  ],
  "abstentions": []
}
```

- `clause_type` is a snake_case identifier. Name clauses the way the answer set does,
  or rely on the synonyms it declares in `clause_aliases`.
- `severity` is `low`, `medium` or `high`.
- `quote` must be copied verbatim from the contract. A quote that is not an exact span
  of the contract (after normalising case, punctuation and whitespace) is a hallucination,
  and any hallucination is a `REJECT`.
- `abstentions` is optional.

The schema is generated from the Pydantic models (`scripts/export_schemas.py`) and CI
fails if the two drift apart, so you can validate against it in your own pipeline.

## 2. Score it against a bundled case

```bash
uv run contract-eval score my-review.json --case nda
```

The bundled cases are `nda`, `saas` and `dpa` (`data/<case>_sample.md`). The
scorecard opens with the release decision, then lists every score; the
[`examples/scorecard.md`](../examples/scorecard.md) table explains the rows.

## 3. Or against your own contract and answer set

```bash
uv run contract-eval score my-review.json --contract my-msa.md --gold my-msa.json
```

Your answer set follows
[`schemas/expected-answer.schema.json`](../schemas/expected-answer.schema.json). The
harness also enforces rules JSON Schema cannot express, and rejects an answer set
that breaks them:

- each clause type appears once;
- every risk flag names a declared clause type and has exactly one non-blank
  `severity_rationale` entry;
- if you give `clause_anchors` (a verbatim phrase locating each clause, used for span
  coverage), there is exactly one per clause type;
- each alias targets a declared clause type and does not shadow one.

The bundled answer sets in `expected/` are worked examples, and
[ANNOTATION_GUIDELINE.md](ANNOTATION_GUIDELINE.md) explains how they were written.

Scoring your own case runs the same code as a bundled one. The result is marked
**comparison only, not certifiable** (`"comparison_only": true`,
`"eligible_for_certification": false` in the JSON), the same rule `score-output`
applies when a captured review's inputs have drifted: the harness can vouch for its
scorer, not for an answer set it has not reviewed. Keeping your answer sets private
also keeps them out of model training data.

## Options and exit status

| Option | Effect |
|---|---|
| `--aliases on\|off` | apply the answer set's declared clause synonyms (default `on`, as the release policy does) |
| `--format markdown\|json` | print the scorecard, or the sealed JSON result with its `result_sha256` |
| `--out DIR` | also write `score-<case>.md` and `score-<case>.json` to `DIR` |
| `--fail-on reject\|human-review` | the lowest decision that exits 1 (default `reject`) |

| Exit status | Meaning |
|---|---|
| 0 | `PILOT_ELIGIBLE`, or `HUMAN_REVIEW_REQUIRED` under the default `--fail-on reject` |
| 1 | `REJECT`, or `HUMAN_REVIEW_REQUIRED` with `--fail-on human-review` |
| 2 | the review, contract or answer set could not be read or parsed |

`PILOT_ELIGIBLE` supports a supervised pilot at most. It never authorizes reliance on
a review, and every flagged risk and citation still needs a qualified lawyer.

## From Python or pytest

The command is a thin wrapper over the Python API:

```python
from contract_eval import evaluate_review, load_case

result = evaluate_review("my-review.json", load_case(contract="my-msa.md", gold="my-msa.json"))
print(result.verdict, result.comparison_only, result.scores["citation_grounding"])
```

In a test suite, `assert_review_passes` from the bundled pytest plugin fails the test
with the blockers and review items; see
[`examples/test_my_reviewer.py`](../examples/test_my_reviewer.py).

## Already have a captured review?

A live run captures every adapter attempt in an envelope with integrity hashes.
Verify and re-score such a capture with
`contract-eval score-output --input <capture>.json` instead;
see [live-runs-and-capture.md](live-runs-and-capture.md).
