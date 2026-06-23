# contract-review-eval-harness

Evaluation harness for legal AI contract review — clause scoring, citation grounding, hallucination counts, against a gold answer set. Not legal advice; data is synthetic.

> **If you don't code:** scroll to [What the demo produces](#what-the-demo-produces). This repo ships a sample output you can read in the browser. The point isn't the code; it's whether the legal work is structured, cited, reviewable, and testable.

![demo](docs/demo.png)

## Run it

```bash
git clone https://github.com/sebastianfoerste/contract-review-eval-harness
cd contract-review-eval-harness
make install && make test
make demo
```

Runs end to end, offline and deterministically.

## What the demo produces

The demo writes a scorecard with clause-level scoring, citation-grounding assessment, and hallucination detection. In the sample run, the harness catches a fabricated citation and marks the output for rejection. You can read the committed sample output: [`examples/scorecard.md`](examples/scorecard.md) and [`examples/scorecard.json`](examples/scorecard.json).

```markdown
# Contract Review Eval Scorecard — nda

## Scores

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.83 | predicted clause types that were expected |
| Clause recall | 1.00 | expected clause types that were found |
| Clause F1 | 0.91 | harmonic mean of precision and recall |
| Risk-flag accuracy | 0.50 | risky clauses flagged at the expected severity |
| Citation grounding | 0.80 | 0/0 quotes found verbatim in the source |
| Hallucination count | 1 | cited quotes not present in the source |

## Failure modes checked

- Over-extraction — clause precision below 1.00.
- Missed clause — clause recall below 1.00.
- Wrong severity — risk-flag accuracy below 1.00.
- Fabricated citation — hallucination count above 0.
```

In the sample run, the harness catches a fabricated citation and marks the output for rejection.

## What it checks / does

| Check / Metric | Focus | Verification Method |
|---|---|---|
| Clause Precision / Recall | Extraction accuracy | Compares predicted clause types to a gold standard set |
| Risk-Flag Accuracy | Severity grading | Checks if predicted risk severities match expected values |
| Citation Grounding | Hallucination tracking | Validates that quoted text segments exist verbatim in the source document |

---

> **What workflow does this improve?** First-pass contract review (clause extraction, risk flags, citations).
> **Who is the user?** A Legal Engineer or counsel deciding whether AI review output is trustworthy enough to rely on.
> **Where does human review happen?** Always. The scorecard tells a lawyer where to look; it never replaces sign-off.
> **What is blocked until approval?** Reliance. A non-zero hallucination count means a citation must be rejected before use.
> **What would I tell Product?** Which failure mode dominates — over-extraction, wrong severity, or fabricated citations — so Engineering knows what to fix first.

## Problem

"The AI reviews contracts" is a demo, not a claim you can take to a top firm. The question
that earns trust is: *how do you know the review is any good?* This harness answers that.
It scores AI review output against an expected answer set and counts the failures that
matter most in legal work — a flagged risk at the wrong severity, a citation that is not
actually in the document.

## What this proves

- I measure quality, I do not assert it: every dimension is a number against a gold set.
- I treat hallucination as a first-class metric, not an afterthought — a fabricated citation is counted and called out.
- I keep a human-review gate explicit: the scorecard ends with what a lawyer must confirm.
- I build for reproducibility: the default path is offline and deterministic, so a reviewer runs the demo with no API key.

## Demo path

```bash
make install            # uv sync
make test               # the scorer is unit-tested
make demo               # writes scorecard.md for the NDA case
uv run python -m contract_eval evaluate --case saas   # the SaaS case
```

## Sample scorecard (NDA)

The NDA stub is deliberately imperfect — it extracts a clause that is not in the contract,
flags one clause at the wrong severity, and cites one quote that does not appear in the
source. The harness catches all three:

![Scorecard: the harness scores clause F1 0.91, citation grounding 4/5, and flags one fabricated citation for rejection](docs/scorecard.svg)

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.83 | extracted a spurious `indemnification` clause |
| Clause recall | 1.00 | found all five expected clause types |
| Clause F1 | 0.91 | |
| Risk-flag accuracy | 0.50 | flagged `definition` low; expected medium |
| Citation grounding | 0.80 | 4 of 5 quotes found verbatim |
| Hallucination count | 1 | one cited quote is not in the contract |

A perfect-looking model would score 1.00 across the board. The point of the harness is
that this one does not, and you can see exactly why.

## Use cases

- **NDA** (`--case nda`) — confidentiality, definition, term, return/destruction, governing law.
- **SaaS agreement** (`--case saas`) — service levels, data protection, limitation of liability, term, auto-renewal.

Both generalize beyond any single regulatory regime, which is why they sit ahead of
domain-specific contracts here.

## How a Legal Engineer would use this in a customer meeting

A firm asks whether they can trust the tool on their NDAs. You do not argue — you run the
harness on a representative NDA and put the scorecard on screen. The conversation moves
from "is AI safe" to "here is the citation-grounding rate, here is the one hallucination we
caught, and here is the human-review step that gates reliance." That is a procurement
conversation a general counsel can sign off on.

## How it works

```
contract (data/<case>_sample.md)
        │
        ▼
   adapter  ──  StubAdapter (fixture, default)  or  LiveAdapter (--live, Anthropic)
        │
        ▼
  ReviewOutput  ── scored against expected/<case>.json
        │
        ▼
   scorer  ──  clause P/R/F1 · risk-flag accuracy · citation grounding · hallucination count
        │
        ▼
  scorecard.md
```

`--live` is strictly optional. The Anthropic SDK is imported lazily; the default offline
path never needs it or an API key.

## Synthetic data statement

Every contract under `data/` is synthetic and fabricated for evaluation. No real agreement,
client, or personal data. See [`data/README.md`](data/README.md).

## Limitations

- The harness measures the review *method*, not a public-benchmark score. It is not a leaderboard.
- Clause matching is by type, and citation grounding is a verbatim-substring check — deliberately simple and transparent, not semantic.
- The shipped fixtures are stubs. Real evaluation depth comes from expanding `expected/` and running `--live`.

## Stack

Python 3.12+, Pydantic v2, pytest, managed with `uv`. Optional live adapter uses the
Anthropic SDK behind a flag.
