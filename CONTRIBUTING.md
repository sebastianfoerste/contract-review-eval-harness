# Contributing

This is a personal, public-safe prototype. Issues, corrections and pull requests are
welcome. There are three main ways to help: add a case, add an adapter, or volunteer as
an annotator. Each has an issue form under **New issue**.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

1. **Synthetic data only.** Never add real client data, privileged material, negotiation
   history or personal data. This applies to contracts, answer sets, fixtures, issues and
   pull requests.
2. **Deterministic by default.** Same input, same output. No network or model call on the
   default path: tests, scoring and the certificate run offline with no API key.
3. **Grounded findings.** Every clause, risk-flag and citation finding is scored against a
   hand-authored answer set, and every citation must be an exact span of the contract.
4. **Not legal advice.** Keep the framing as a review and evaluation artifact.

## Set up and check

```bash
make install   # uv sync
make test      # pytest
make check     # the tests plus the drift and verification checks CI runs
```

Everything in `make check` must pass before a pull request except its last step,
`web-check`. That step compares the scorer with the maintainer's `contract-eval-web`
checkout and fails when that sibling directory is absent. CI does not run it.

If an output changes, regenerate the committed artifacts in `examples/` and commit them
with your change: `uv run python -m contract_eval evaluate --case nda --out examples` (add
`--format json` for `scorecard.json`) for the committed scorecard, `make certificate` for
the release certificate, `make robustness` for the adversarial report. Regenerate the
parity vectors (`make parity-vectors`) only for an intended scoring change. Regenerate
the regression baseline (`make regression-baseline`) only when a score moves on purpose
or a case is added: CI fails every run that scores worse than
`examples/regression-baseline.json`. `make demo` prints the NDA scorecard. It writes
`scorecard.md` and `run-provenance.json` to the repository root and
`history/run_<timestamp>.json`, all ignored and none committed. Every evaluate run writes
its `history/` under `--out`, so the scorecard command above also leaves an ignored
`examples/history/`. The metric definitions are in [docs/metrics.md](docs/metrics.md).

## Path 1: add a case

A case is one synthetic contract plus the answer set it is scored against. The steps
are in the docstring of `src/contract_eval/cases.py`:

1. `data/<case>_sample.md`: the synthetic contract.
2. `expected/<case>.json`: the hand-authored answer set (clause types, risk flags with
   severities and rationales, clause aliases, and one verbatim anchor per clause).
3. `fixtures/<case>_stub.json`: the deterministic offline adapter output. It is
   deliberately imperfect, as described in [`data/README.md`](data/README.md).
4. Optionally, scenarios naming the case in `robustness/campaign.v1.json`.
5. One entry in `ALL_CASES` in `src/contract_eval/cases.py`. Every consumer derives its
   case list from it.

Then run `make anchor-check`, `make certificate`, `make regression-baseline` and
`make check`, review the changed certificate and regression baseline, and commit them.
[docs/ANNOTATION_GUIDELINE.md](docs/ANNOTATION_GUIDELINE.md) explains how to write the
agreement, choose clause types, assign severities, declare aliases and write anchors.
[`candidates/`](candidates/README.md) shows two cases waiting for their answer sets.

## Path 2: add an adapter

An adapter connects the harness to a review tool or model. Check first whether you need
one: `contract-eval score` grades a review JSON your tool already wrote, `--adapter
command` runs any program that reads the contract on stdin and prints review JSON, and
`--adapter openai-compatible` covers any Chat Completions endpoint (see
[live runs and capture](docs/live-runs-and-capture.md)).

A new adapter implements the `Adapter` protocol in `src/contract_eval/adapters/base.py`:

- `review(source_text, case) -> ReviewOutput`
- `capture(source_text, case) -> (ProviderRequest, ProviderResponse, raw_text)`, the
  provenance-carrying path. `review()` should be a thin wrapper over it.

Rules:

- Import the provider SDK lazily, inside the adapter, as `get_adapter` does for
  `LiveAdapter`. The default install must not need it; put it in an optional extra.
- No network call and no API key on the default path. A live run is strictly opt-in.
- Register its name in `ADAPTER_NAMES`, `get_adapter` and `adapter_identifier` in
  `src/contract_eval/adapters/__init__.py`, so `--adapter <name>` selects it and
  provenance names it.
- Add a test that runs with no API key and no network, like
  `tests/test_live_adapter_contract.py`, or against a local fake server, like
  `tests/test_openai_compat_adapter.py`.

## Path 3: volunteer as an annotator

The answer sets encode one reviewer's judgment. A second, independent annotation is the
most valuable contribution a lawyer can make. See [annotations/README.md](annotations/README.md)
for the status.

1. Open an issue with the annotator form.
2. You receive the annotation pack (`annotations/pack/`): the synthetic contracts and
   [the annotator guideline](annotations/pack/ANNOTATOR_GUIDELINE.md).
3. Annotate blind. Work only from the pack, not from the repository, model output or
   anyone else's annotation.
4. Return the annotation. Disagreements are adjudicated in writing before anything
   becomes gold.

Annotate only the synthetic contracts in the pack. Never paste real client data into an
issue or an annotation.

## Reporting an issue

Be specific: the command, the case, what you expected and what happened. For a scoring
question, name the scorecard row and the clause, risk flag or citation involved.
Corrections to an answer set are the most valuable kind of report.
