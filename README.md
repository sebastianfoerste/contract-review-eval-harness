# contract-review-eval-harness

[![CI](https://github.com/sebastianfoerste/contract-review-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/sebastianfoerste/contract-review-eval-harness/actions/workflows/ci.yml)

See [CASE_STUDY.md](CASE_STUDY.md) for the problem, controls, and limitations.

Evaluation harness for legal AI contract review: clause scoring, citation grounding and hallucination counts against a gold answer set. Not legal advice; data is synthetic.

**Public-safety posture:** synthetic contracts only, visible source provenance in every citation check, an explicit human review gate before reliance, and no legal advice.

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

The demo writes a scorecard with clause-level scoring, citation-grounding assessment and unsupported-citation detection. In the sample run, the harness catches a fabricated citation and marks the output for rejection. You can read the committed sample output in [`examples/scorecard.md`](examples/scorecard.md) and [`examples/scorecard.json`](examples/scorecard.json).

```markdown
# Contract Review Eval Scorecard: nda

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.83 | predicted clause types that were expected |
| Clause recall | 1.00 | expected clause types that were found |
| Clause F1 | 0.91 | harmonic mean of precision and recall |
| Risk-flag accuracy | 0.50 | risky clauses flagged at the expected severity |
| Citation grounding | 0.80 | 4/5 quotes grounded in the source |
| Hallucination count | 1 | cited quotes not grounded in the source |
```

## What it checks

- Clause precision and recall.
- Risk-flag accuracy.
- Citation grounding.
- Unsupported or fabricated citations.

## Problem

"The AI reviews contracts" is a demo, not a claim a serious reviewer can rely on. The useful question is: how do you know the review is any good? This harness scores AI review output against an expected answer set and counts the failures that matter most in legal work.

## What this proves

- Quality is measured, not asserted.
- Unsupported citations are treated as first-class failures.
- The scorecard ends with human-review instructions.
- The default path is offline and deterministic, so a reviewer runs the demo with no API key.

## Demo path

```bash
make install
make test
make demo
uv run python -m contract_eval evaluate --case saas
```

## Optional live-model run

The default path is a deterministic stub. The optional live adapter can score output from a frontier model against the same gold answer set:

```bash
uv sync --extra live
export MODEL_API_KEY=...
make demo-live
```

A captured run against a frontier model is committed in the examples folder as a dated snapshot. Live output is non-deterministic; the committed file is not a stable benchmark.

## Use cases

- NDA: confidentiality, definition, term, return/destruction, governing law.
- SaaS agreement: service levels, data protection, limitation of liability, term, auto-renewal.

## Synthetic data statement

Every contract under `data/` is synthetic and fabricated for evaluation. No real agreement, client, or personal data is included.

## Limitations

This is a public-safe prototype, not a production benchmark or leaderboard. The answer sets are synthetic and intentionally small. It covers two contract types today. Broader coverage comes from expanding expected answer sets and adding versioned benchmark runs.

## Stack

Python, Pydantic, pytest and uv. The optional live adapter is behind a flag and the default offline path does not need an API key.

## Human-authored legal judgment

AI tools assisted the implementation, but the parts that carry the value are human-authored: the gold answer sets, risk taxonomy, clause types and citation-grounding rules. The point of this repository is not code volume; it is showing how legal judgment can be made structured, testable and reviewable.
