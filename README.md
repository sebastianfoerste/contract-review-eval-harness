# contract-review-eval-harness

[![CI](https://github.com/sebastianfoerste/contract-review-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/sebastianfoerste/contract-review-eval-harness/actions/workflows/ci.yml)

**Find out whether an AI contract review is actually good: scores clause coverage, risk severity and citation grounding against a hand-authored gold set, and rejects fabricated citations.**

Offline, deterministic, no API key. Synthetic contracts only. Not legal advice.

![Actual output of make demo: the NDA scorecard](https://raw.githubusercontent.com/sebastianfoerste/contract-review-eval-harness/main/docs/demo.png)

*Actual output of `make demo`, rendered as an image.*

## Quick start

Needs [uv](https://docs.astral.sh/uv/), which fetches a supported Python if none is installed.

```bash
git clone https://github.com/sebastianfoerste/contract-review-eval-harness
cd contract-review-eval-harness
uv sync
uv run python -m contract_eval evaluate --case nda   # writes scorecard.md
```

Score your own tool's review JSON ([schema](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/schemas/review-output.schema.json)) against a bundled contract:

```bash
uv run contract-eval score my-review.json --case nda   # exit 1 on REJECT
```

## Example output

Selected rows from the [NDA scorecard](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/examples/scorecard.md) of the offline stub, which is deliberately imperfect:

| Dimension | Score | Notes |
|---|---:|---|
| Clause F1 | 0.96 | harmonic mean of precision and recall |
| Risk precision | 0.83 | flagged clauses that the gold set treats as risks |
| Severity accuracy | 0.60 | correct severity among jointly identified risks |
| Citation grounding | 0.89 | 8/9 quotes matched as an exact span of the normalised source |
| Hallucination count | 1 | cited quotes not grounded in the source |

The one fabricated citation is a hard `REJECT`.

## Links

- [Overview](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/docs/overview.md): why this exists, what it checks, more commands, how it compares, limitations
- [Metric reference](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/docs/metrics.md)
- [Score your own tool](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/docs/score-your-own-tool.md) and [gate CI on it](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/docs/ci.md)
- [Release certificate and robustness](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/docs/certificate-and-robustness.md)
- [Live runs, capture and replay](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/docs/live-runs-and-capture.md) and the [leaderboard](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/examples/leaderboard.md)
- [Results site](https://sebastianfoerste.github.io/contract-review-eval-harness/) and [playground](https://sebastianfoerste.github.io/contract-review-eval-harness/playground/)
- [Case study](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/CASE_STUDY.md), [changelog](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/CHANGELOG.md), [contributing](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/CONTRIBUTING.md)

Limitations: synthetic contracts, one annotator's gold sets and three contract types; every flagged risk and citation needs a qualified lawyer before reliance ([details](https://github.com/sebastianfoerste/contract-review-eval-harness/blob/main/docs/overview.md#limitations-and-safety)).
