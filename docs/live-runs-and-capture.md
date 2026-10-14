# Live runs, capture and replay

Moved from the README.

## Demo path

```bash
make install
make test
make demo
uv run python -m contract_eval evaluate --case saas
make certificate
make certificate-verify
make robustness
make robustness-check
```

## Optional live-model run

The default path is a deterministic stub. The optional live adapter can score output from a frontier model against the same gold answer set:

```bash
uv sync --extra live
export ANTHROPIC_API_KEY=...
uv run python -m contract_eval robustness --live --runs 3 --out live-results
```

The model is selectable, so the same gold set can be replayed across versions and
compared. Pass `--model`, or set `CONTRACT_EVAL_MODEL`; the default is
`claude-opus-5`. Reasoning effort is set with `CONTRACT_EVAL_EFFORT` (default
`high`) and is recorded in every capture, because it changes the output and a
score is not comparable across two runs that used different levels.

```bash
uv run python -m contract_eval evaluate --case all --live --model claude-opus-5
```

A captured run against a frontier model is committed in the examples folder as a dated snapshot. Live output is non-deterministic; the committed file is not a stable benchmark. Any published comparison must name the model, the date and the harness version, because a score without those three is not reproducible.

Every adapter attempt is now captured before it is parsed. A capture embeds the source
and gold snapshots, the sanitized request, the raw response and the parsed output, each
hashed, and is written atomically before the provider is called. Truncated, malformed,
interrupted and provider-error attempts leave evidence and are never scored.

```bash
uv run python -m contract_eval verify-capture --input captures/<run>/<capture>.json
uv run python -m contract_eval score-output --input <capture>.json --aliases both
```

`score-output` re-scores captured bytes offline through the same `score_review` a live
run uses, so a replayed number proves something about the published one. Current-input
drift fails by default; `--allow-input-drift` reproduces the historical result and marks
it comparison-only and ineligible for certification.

The [2026-09-01 run](../examples/live-run-claude-opus-5-2026-09-01.md) is worth reading for
what it found in the harness rather than in the model. One captured adapter output was
scored twice, with clause aliasing off and on. Identical bytes scored 0.522 and 0.783
clause F1 on the NDA, because clause-type labels were being compared by string equality.
Aliasing raises every score but does not solve it: recall reaches at most 0.818, the map
does not transfer between runs, and it cannot express a gold clause the model split in
two.

`span_coverage` measures the same output without reference to labels. Every gold clause
carries a verbatim anchor locating it in the source, each clause owns the region up to
the next anchor, and a clause counts as covered when a grounded citation lands inside
it. On that measure the same output scores 1.000, 1.000 and 0.900 against label-based
F1 of 0.783, 0.818 and 0.476. It measures citation placement, not comprehension.

That report is generated from the captures by `make live-run-report`, and CI fails on any
drift between the committed file and a fresh generation. It is no longer transcribed by
hand, which is how the retracted 2026-08-28 table came to present two separate
generations as one output scored twice. That record is retained with its comparison
withdrawn.

