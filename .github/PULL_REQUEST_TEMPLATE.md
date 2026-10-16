## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Checklist

- [ ] `make check` passes. Without make: `uv run pytest -q` plus the commands under the `check` target in the `Makefile`.
- [ ] Synthetic data only. No real client data, privileged material or personal data.
- [ ] Committed artifacts are regenerated when outputs change (`make certificate`, `make robustness`; `make parity-vectors` only for an intended scoring change).
- [ ] The default path stays offline and deterministic: no network call, no API key, same input, same output.
- [ ] No secrets or API keys in code, fixtures, captures or logs.
