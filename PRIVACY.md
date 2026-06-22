# Privacy

This harness processes no personal data and no client data.

- Every contract under `data/` is synthetic and invented for evaluation. Party names are fictional.
- The default offline path transmits nothing. The deterministic stub reads bundled fixtures only.
- If you opt into `--live`, the synthetic contract text is sent to the Anthropic API to generate review output. Do not point `--live` at real or confidential contracts.

The harness is built around an explicit human-review gate: it measures and reports on AI
review quality so a qualified lawyer can decide what to rely on. It never stands in for
legal advice.
