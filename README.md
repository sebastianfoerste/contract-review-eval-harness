# contract-review-eval-harness

An evaluation harness for AI contract review. It does not just run a model over a
contract and show the output — it measures the output against a hand-authored answer set
and emits a scorecard: clause precision/recall, risk-flag accuracy, citation grounding,
and a hallucination count. Synthetic contracts only; runs offline and deterministic by
default.

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
