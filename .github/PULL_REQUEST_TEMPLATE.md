## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Checklist

- [ ] Every target in `make check` except `web-check` passes (CONTRIBUTING.md lists them; `web-check` needs the sibling `contract-eval-web` checkout), and so do `uv lock --check`, `uv run ruff check src tests scripts` and `uv run mypy`.
- [ ] Synthetic data only. No real client data, privileged material or personal data.
- [ ] Committed artifacts are regenerated when outputs change (`make certificate`, `make robustness`; `make parity-vectors` only for an intended scoring change; `make regression-baseline` only for an intended score change or a new case).
- [ ] The default path stays offline and deterministic: no network call, no API key, same input, same output.
- [ ] No secrets or API keys in code, fixtures, captures or logs.
