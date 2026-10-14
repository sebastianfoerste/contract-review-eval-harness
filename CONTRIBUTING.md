# Contributing

This is a personal, public-safe prototype. Issues and corrections are welcome.

## Ground rules

1. **Synthetic data only.** Never add real client data, privileged material, negotiation history, or personal data.
2. **Deterministic by default.** Same input, same output. No network or model calls in the core checks/evaluation.
3. **Cited / grounded findings.** Every regulatory finding carries a specific, verifiable citation.
4. **Not legal advice.** Keep the framing as a review / evaluation artifact.

## Working on it

```bash
make install
make test     # must pass before any PR
make demo     # prints the NDA scorecard; writes scorecard.md and run-provenance.json to the repo root and history/run_<timestamp>.json (all ignored)
```

If the output changed, refresh the committed copies in `examples/` and commit them:
`uv run python -m contract_eval evaluate --case nda --out examples` (add `--format json` for
`scorecard.json`), then `make certificate` and `make robustness`.

## Reporting an issue

Be specific: the rule or step, what you expected, and — for regulatory checks — the corrected citation. Citation fixes are the most valuable contribution.
