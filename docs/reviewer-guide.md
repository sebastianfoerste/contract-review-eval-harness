# Reviewer guide

A five-minute path for a reviewer.

1. **Run it.** `make install && make demo`. This writes `scorecard.md` for the NDA case and
   prints it.
2. **Read the scorecard.** Note that it is not perfect: clause precision 0.92, severity
   accuracy 0.60 (legacy risk-flag accuracy 0.50), one hallucinated citation. That is by
   design.
3. **See why.** Open `fixtures/nda_stub.json`, the stub model output. It extracts a clause
   that is not in the contract (`indemnification`), rates `permitted_disclosure` medium and
   `assignment` low where the answer set says high, flags `governing_law`, which the answer
   set does not treat as a risk, misses the `notices` risk, and cites a quote
   (`notices shall be deemed received...`) that does not appear in `data/nda_sample.md`.
4. **See how it is measured.** Open `src/contract_eval/scorer.py`. Small pure functions.
   Citation grounding requires each quote to occur as an exact span of the normalised
   source, with no fuzzy fallback. It is transparent, intentionally shallow, and not magic.
5. **Run the second case.** `uv run python -m contract_eval evaluate --case saas`.
6. **The tests.** `make test` runs the scorer and CLI unit tests, including one that
   asserts the seeded errors are caught end to end.

What to check: the metrics are explainable, hallucinations are counted, and nothing here
claims to replace a lawyer. The scorecard ends with what a human must confirm.

To run against a real model instead of the stub: `uv add anthropic`, set
`ANTHROPIC_API_KEY`, then add `--live`.
