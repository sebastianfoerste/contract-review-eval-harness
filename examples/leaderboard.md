# Contract review leaderboard

**Generated from committed review outputs. Do not edit by hand.**

Regenerate with `make leaderboard`. Leaderboard digest: `be501ee986f3b891daa415fc1ad01562f6957f074a165b402d5d1d204c5e7e78`.

- Release policy: `contract-review-eval.strict-legal-release-policy.v2`
- Declared clause aliases: on
- Date is when the output was produced. Harness is the scorer version that
  computed the row, the same for every row; it is not the version that produced the output.
- Scores are means across a row's cases; hallucinations are summed.
- Verdict is the worst case decision; per-case decisions are in `leaderboard.json`.
- Cost is the run's total across its cases and latency the mean per case; both
  read n/a unless every capture in the row records them.
- Synthetic contracts only. A verdict here ranks committed outputs for comparison;
  it is not a release certificate and establishes no fitness for contract review.

| Rank | Tool / model | Kind | Date | Harness | Clause F1 | Span coverage | Risk F1 | Severity accuracy | Citation grounding | Hallucinations | Cost (USD) | Latency (ms) | Verdict |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | claude-opus-5 | captured | 2026-09-01 | 0.7.0rc1 | 0.692 | 0.967 | 0.560 | 0.889 | 1.000 | 0 | n/a | n/a | HUMAN_REVIEW_REQUIRED |
| 2 | stub adapter (deterministic baseline) | baseline | n/a | 0.7.0rc1 | 0.955 | 0.718 | 0.922 | 0.590 | 0.884 | 3 | n/a | n/a | REJECT |

## Per-case decisions

| Tool / model | Date | Case | Decision | Blockers | Review items |
|---|---|---|---|---:|---:|
| claude-opus-5 | 2026-09-01 | dpa | HUMAN_REVIEW_REQUIRED | 0 | 4 |
| claude-opus-5 | 2026-09-01 | nda | HUMAN_REVIEW_REQUIRED | 0 | 4 |
| claude-opus-5 | 2026-09-01 | saas | HUMAN_REVIEW_REQUIRED | 0 | 5 |
| stub adapter (deterministic baseline) | n/a | dpa | REJECT | 2 | 2 |
| stub adapter (deterministic baseline) | n/a | nda | REJECT | 2 | 4 |
| stub adapter (deterministic baseline) | n/a | saas | REJECT | 2 | 3 |
