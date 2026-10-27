# contract-review-eval-harness

A harness that measures the quality of AI contract review — it does not perform review
for show. A model runs through an adapter, its output is scored against a hand-authored
answer set, and a scorecard is emitted. Synthetic contracts only; deterministic by default.

## Layout
- `src/contract_eval/models.py` — Pydantic models: `ReviewOutput` (clauses, risk flags, citations) and `ExpectedAnswer`. Single source of truth for shapes.
- `src/contract_eval/adapters/` — `Adapter` protocol, `StubAdapter` (fixtures), lazy `LiveAdapter` (Anthropic), `OpenAICompatibleAdapter` (stdlib HTTP), `CommandAdapter` (any program: contract on stdin, review JSON on stdout); `get_adapter(live, model, choice)` behind `--adapter` (`--live` stays an alias for `--adapter anthropic`).
- `src/contract_eval/scorer.py` — pure scoring functions: clause P/R/F1, risk-flag accuracy, citation grounding, hallucination count. Unit-tested.
- `src/contract_eval/api.py` — the Python API: `score_review`, `load_case`, `evaluate_review`, `Verdict`; exported from `contract_eval/__init__.py`. The CLI and the pytest plugin call it, so all three reach the same numbers.
- `src/contract_eval/pytest_plugin.py` — `assert_review_passes` and the `contract_case` fixture, registered under the `pytest11` entry point.
- `src/contract_eval/cli.py` — `evaluate()` pipeline, `score()` for any tool's plain review JSON (`contract-eval score`), argparse `main`. Maintainer commands sit under `contract-eval dev` and stay accepted, unlisted, at the top level. `scorecard.py` renders markdown.
- `data/<case>_sample.md` — synthetic contracts. `expected/<case>.json` — gold answers. `fixtures/<case>_stub.json` — stub model output. The wheel ships byte-identical copies; `src/contract_eval/paths.py` resolves the working directory first, then an editable checkout, then that bundled copy.
- `src/contract_eval/schemas.py` — JSON Schemas for a review and an answer set, generated from the models into `schemas/`; `make schemas-check` rejects drift.
- `action.yml` + `src/contract_eval/github_action.py` — the composite GitHub Action that gates another repository's CI on `contract-eval score`.
- `scripts/build_leaderboard.py` (`examples/leaderboard.*`, drift-checked in CI) and `scripts/build_site.py` (static `site/` for GitHub Pages).
- `src/contract_eval/matter.py`, `matter_scorer.py`, `matter_experiment.py`, `matter_cli.py`, `reviewer_sessions.py` — the matter path: several documents, rounds, conditions, evidence-bound scoring per document. See `docs/MATTER_EVALUATION.md`.
- `matters/<id>/` — a synthetic matter: `matter.json` manifest, `documents/`, `prompts/`, `expected/<round>.json`, optional `fixtures/` and `reviews/`. Contracts under `data/` are referenced by path, never copied. The wheel does not ship `matters/`, so the matter path runs from a checkout.
- `tests/` — pytest. `tests/fixtures/mini_matter/` is a toy matter whose answers are test data.

## Rules
- Python 3.11+ (CI runs 3.11, 3.12 and 3.13), type hints throughout, Pydantic for data models.
- Default path is offline and deterministic: no network, no API key. `--live` is strictly opt-in and must never break default paths (import the SDK lazily).
- Synthetic data only. Never add a real agreement or client data.
- The scorer is the core logic — keep functions pure and tested. The stub fixture deliberately contains one over-flag and one fabricated citation so the scorecard always demonstrates an imperfect score being caught.
- Matter answers under `matters/<id>/expected/` are written by the reviewing lawyer. Never generate them, and never write a stub fixture for a round whose answers are pending. After editing a matter document or an answer quote, run `uv run python scripts/matter_sync.py --write`.
- The companion web explorer (`contract-eval-web`) consumes exported synthetic cases and parity vectors. Never drift contract data or scoring semantics without running `make web-check` or `make web-export`.
- `examples/web-parity-vectors.json` pins the scorer output in CI, where the web repository is absent. Regenerate it with `make parity-vectors` only for an intended scoring change, then run `make web-export`.

## Commands
`make install` (uv sync) · `make test` · `make demo` (NDA scorecard) · `make demo-live` · `make parity-check` · `make schemas` · `make leaderboard` · `make site` · `make web-check` · `make web-export` · `make matter-check` · `make matter-demo` · `make check`.

