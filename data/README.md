# Synthetic contracts

Every contract in this folder is **synthetic** and drafted for evaluation only.

- No real agreement, client, or counterparty is represented. Party names are invented.
- No confidential or personal data.

Each case has three files:

- `data/<case>_sample.md` — the synthetic contract.
- `expected/<case>.json` — the hand-authored answer set (which clause types should be found, which clauses are risky).
- `fixtures/<case>_stub.json` — a deterministic stub of model output, used so the harness runs offline with no API key.

The stub fixtures are intentionally imperfect — they contain over-extraction, a wrong
severity, and a fabricated citation — so the scorecard demonstrates the harness catching
real failure modes rather than rubber-stamping perfect output.
