# Privacy

This harness processes no personal data and no client data.

- Every contract under `data/` and every document under `matters/` is synthetic and invented for evaluation. Party names are fictional.
- The default offline path transmits nothing. The deterministic stub reads bundled fixtures only.
- If you opt into `--live`, synthetic text is sent to the Anthropic API to generate review output: the contract for a case, and for `matter-evaluate` every document a scored condition may see. Do not point `--live` at real or confidential documents.

The harness is built around an explicit human-review gate: it measures and reports on AI
review quality so a qualified lawyer can decide what to rely on. It never stands in for
legal advice.
