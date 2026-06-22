# Reviewer guide

A five-minute path for a reviewer.

1. **Run it.** `make install && make demo`. This writes `scorecard.md` for the NDA case.
2. **Read the scorecard.** Six dimensions. Note that it is not perfect: clause precision
   0.83, risk-flag accuracy 0.50, one hallucinated citation. That is by design.
3. **See why.** Open `fixtures/nda_stub.json` — the stub model output. It extracts a clause
   that is not in the contract (`indemnification`), flags `definition` at the wrong severity,
   and cites a quote (`automatically renews...`) that does not appear in `data/nda_sample.md`.
4. **See how it is measured.** Open `src/contract_eval/scorer.py`. Four small pure
   functions. Citation grounding is a verbatim substring check — transparent, not magic.
5. **Run the second case.** `uv run python -m contract_eval evaluate --case saas`.
6. **The tests.** `make test` runs the scorer and CLI unit tests, including one that
   asserts the seeded errors are caught end to end.

What to check: the metrics are explainable, hallucinations are counted, and nothing here
claims to replace a lawyer — the scorecard ends with what a human must confirm.

To run against a real model instead of the stub: `uv add anthropic`, set
`ANTHROPIC_API_KEY`, then add `--live`.
