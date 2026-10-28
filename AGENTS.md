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
- `scripts/build_leaderboard.py` (`examples/leaderboard.*`, drift-checked in CI) and `scripts/build_site.py` (static `site/` for GitHub Pages; with `--wheel` it adds the playground).
- `playground/` — the browser playground: a static page whose worker installs the wheel into Pyodide and scores through `playground/score.py`, which calls `contract_eval.cli.score`. Keep its exported JSON identical to the CLI's (`tests/test_playground.py`).
- `src/contract_eval/candidates.py`, `candidate_annotation.py`, `candidate_adjudication.py`, `candidate_experiment.py`, `candidate_budget.py` — the separate native My Counsel track: scoring one recording; blind annotation pack and DRAFT compiler for one annotation; written adjudication between two annotations, the only route to an independently reviewed reference; preregistered experiments with refusals and denominators; cumulative EUR spend ledger. Corpus, pack, worked example and ledger live under `candidates/mycounsel/`; see its README. Never in `ALL_CASES` or a certificate. Playbooks and documents are written by `candidates/mycounsel/build_fixtures.py`: change them there and run it. After changing the guideline, a playbook, a document or the source register run `make candidate-pack` and `make candidate-bundle`, then rebuild `experiments/replay-dry-run` (remove the folder, plan with the arguments in its `experiment.json`, copy `replay-run.json` into `attempts/baseline/commercial-base-r1.json`, register, aggregate). After a change to the commercial playbook or the base document, `replay-run.json` no longer matches the corpus and is recorded again first, with the replay mode of the ZuRecht recorder. Once the pack has been sent these files are frozen. An attempt file is never deleted. An empty slot file means a paid call that is still out or ended without a recording; only `register --lost <slot>` binds it, and never while the call may be out. After changing an experiment's inputs re-aggregate its report. `make candidate-check` runs the track's tests.
- `tests/` — pytest.

## Rules
- Python 3.11+ (CI runs 3.11, 3.12 and 3.13), type hints throughout, Pydantic for data models.
- Default path is offline and deterministic: no network, no API key. `--live` is strictly opt-in and must never break default paths (import the SDK lazily).
- Synthetic data only. Never add a real agreement or client data.
- The scorer is the core logic — keep functions pure and tested. The stub fixture deliberately contains one over-flag and one fabricated citation so the scorecard always demonstrates an imperfect score being caught.
- The companion web explorer (`contract-eval-web`) consumes exported synthetic cases and parity vectors. Never drift contract data or scoring semantics without running `make web-check` or `make web-export`.
- `examples/web-parity-vectors.json` pins the scorer output in CI, where the web repository is absent. Regenerate it with `make parity-vectors` only for an intended scoring change, then run `make web-export`.
- `examples/regression-baseline.json` is the committed run that CI and `make regression-check` compare a fresh `evaluate --case all` run against. `compare` exits 1 when a metric it tracks is worse for any case the baseline records. Regenerate the baseline with `make regression-baseline` only when a change moves a score on purpose or adds a case, and commit it with that change; `make test` fails until it records the current scores of every case in `ALL_CASES`. Never regenerate it to get past a regression. `evaluate` writes `history/run_<timestamp>.json` under its `--out` directory, and those runs stay untracked.

## Commands
`make install` (uv sync) · `make test` · `make demo` (NDA scorecard) · `make demo-live` · `make parity-check` · `make regression-check` · `make schemas` · `make leaderboard` · `make site` · `make web-check` · `make web-export` · `make check`.

