# contract-review-eval-harness

A harness that measures the quality of AI contract review — it does not perform review
for show. A model runs through an adapter, its output is scored against a hand-authored
answer set, and a scorecard is emitted. Synthetic contracts only; deterministic by default.

## Layout
- `src/contract_eval/models.py` — Pydantic models: `ReviewOutput` (clauses, risk flags, citations) and `ExpectedAnswer`. Single source of truth for shapes.
- `src/contract_eval/adapters/` — `Adapter` protocol, `StubAdapter` (fixtures), lazy `LiveAdapter`, `get_adapter(live)`.
- `src/contract_eval/scorer.py` — pure scoring functions: clause P/R/F1, risk-flag accuracy, citation grounding, hallucination count. Unit-tested.
- `src/contract_eval/cli.py` — `evaluate()` pipeline + argparse `main`. `scorecard.py` renders markdown.
- `data/<case>_sample.md` — synthetic contracts. `expected/<case>.json` — gold answers. `fixtures/<case>_stub.json` — stub model output.
- `tests/` — pytest.

## Rules
- Python 3.12+, type hints throughout, Pydantic for data models.
- Default path is offline and deterministic: no network, no API key. `--live` is strictly opt-in and must never break default paths (import the SDK lazily).
- Synthetic data only. Never add a real agreement or client data.
- The scorer is the core logic — keep functions pure and tested. The stub fixture deliberately contains one over-flag and one fabricated citation so the scorecard always demonstrates an imperfect score being caught.

## Commands
`make install` (uv sync) · `make test` · `make demo` (NDA scorecard) · `make demo-live`.
