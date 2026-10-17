# Reviewer guide

A five-minute path for a reviewer.

1. **Run it.** `make install && make demo`. This writes `scorecard.md` for the NDA case.
2. **Read the scorecard.** Fourteen rows in the Scores table. Note that it is not perfect:
   clause precision 0.92, severity accuracy 0.60, legacy risk-flag accuracy 0.50, one
   hallucinated citation. That is by design.
3. **See why.** Open `fixtures/nda_stub.json`, the stub model output. It extracts a clause
   that is not in the contract (`indemnification`), flags `assignment` as low and
   `permitted_disclosure` as medium where `expected/nda.json` says high, leaves `notices`
   unflagged, flags `governing_law` although the gold answer does not treat it as a risk,
   and cites a quote (`notices shall be deemed received...`) that does not appear in `data/nda_sample.md`.
4. **See how it is measured.** Open `src/contract_eval/scorer.py`. Six pure scoring
   functions (`clause_scores`, `risk_flag_accuracy`, `risk_metrics`, `citation_grounding`,
   `count_hallucinations`, `span_coverage`) plus text-normalisation and span-matching
   helpers. A quote counts as grounded only when it is an exact contiguous span of the
   source after case, punctuation and whitespace are normalised. There is no token-overlap
   fallback. It is transparent, intentionally shallow, and not magic.
5. **Run the second case.** `uv run python -m contract_eval evaluate --case saas`.
6. **The tests.** `make test` runs the scorer and CLI unit tests, including one that
   asserts the seeded errors are caught end to end.

What to check: the metrics are explainable, hallucinations are counted, and nothing here
claims to replace a lawyer. The scorecard's "Human review required" section states what a
human must confirm.

To run against a real model instead of the stub: `uv sync --extra live`, set
`ANTHROPIC_API_KEY`, then add `--live`.
