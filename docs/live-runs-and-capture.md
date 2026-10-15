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

## Choosing an adapter

`evaluate`, `robustness` and `evaluate-obligations` take `--adapter`:

| `--adapter` | What produces the review | Needs |
|---|---|---|
| `stub` (default) | the committed fixture; offline and deterministic | nothing |
| `anthropic` | the Anthropic API; `--live` is an alias kept for existing scripts | `uv sync --extra live`, `ANTHROPIC_API_KEY` |
| `openai-compatible` | any Chat Completions endpoint: OpenAI, Mistral, vLLM, Ollama, ... | `--model`; `--base-url`; a key unless the server is local |
| `command` | any program you point it at | `--command` |

```bash
# A local Ollama server: no key needed.
uv run python -m contract_eval evaluate --case all --adapter openai-compatible \
  --base-url http://127.0.0.1:11434/v1 --model llama3.1
# A hosted endpoint, with the key read from a variable you name.
uv run python -m contract_eval evaluate --case all --adapter openai-compatible \
  --base-url https://api.mistral.ai/v1 --api-key-env MISTRAL_API_KEY --model mistral-large-latest
```

The OpenAI-compatible adapter uses the standard library, so it adds no dependency. The
base URL defaults to `OPENAI_BASE_URL`, then `https://api.openai.com/v1`; the key comes
from the variable named by `--api-key-env` (default `OPENAI_API_KEY`) and is sent as a
bearer token only when that variable is set. Only the variable's name is held; the key
is never logged or written into a capture. Redirects are not followed, so the key is
only ever sent to the configured host: a `30x` reply is an error that names the
redirect target, which you can pass as `--base-url` instead. It sends the same prompt as the Anthropic
adapter plus the `ReviewOutput` JSON schema, both in the prompt and as
`response_format`, because not every compatible server enforces the latter. OpenAI's
reasoning models want `max_completion_tokens` rather than `max_tokens`; set
`CONTRACT_EVAL_MAX_TOKENS_FIELD=max_completion_tokens` for those. The adapter id recorded
in provenance is `openai-compatible:<model>@<base-url>`.

### The command adapter contract

The command adapter puts any product behind the harness. The program receives the
contract text on stdin and the case name in `CONTRACT_EVAL_CASE`, and prints one
`ReviewOutput` JSON document on stdout (the schema in `src/contract_eval/models.py`). The
command is split with `shlex` and run without a shell, with the
`CONTRACT_EVAL_TIMEOUT_SECONDS` timeout (default 300). A non-zero exit, a timeout, output
that is not JSON or JSON that does not match the schema each fail the run with the cause
and, for a failed exit, the end of stderr. A five-line wrapper around a vendor API:

```python
import json, os, sys, urllib.request
req = urllib.request.Request(os.environ["VENDOR_URL"], data=sys.stdin.read().encode(),
                             headers={"Authorization": f"Bearer {os.environ['VENDOR_KEY']}"})
reply = json.load(urllib.request.urlopen(req, timeout=300))
print(json.dumps({"clauses": reply["clauses"], "risk_flags": reply["risks"], "citations": reply["quotes"]}))
```

```bash
uv run python -m contract_eval evaluate --case all --adapter command --command "python my_wrapper.py"
```

The command line is recorded in provenance as `command:<command>`, so keep credentials in
the environment, as above, and never in the command itself. The evidence-bound
`evaluate-obligations` path upgrades the printed v1 review the same way it upgrades the
stub fixture.

A captured run against a frontier model is committed in the examples folder as a dated snapshot. Live output is non-deterministic; the committed file is not a stable benchmark. Any published comparison must name the model, the date and the harness version, because a score without those three is not reproducible.

Every adapter attempt is now captured before it is parsed. A capture embeds the source
and gold snapshots, the sanitized request, the raw response and the parsed output, each
hashed, and is written atomically before the provider is called. Truncated, malformed,
interrupted and provider-error attempts leave evidence and are never scored.

```bash
uv run python -m contract_eval verify-capture --input captures/<run>/<capture>.json
uv run python -m contract_eval score-output --input <capture>.json --aliases both
```

A capture also records `latency_seconds`, the wall-clock time around the adapter call
measured with `time.perf_counter` (failed calls included, so a timeout shows), and a
`cost` estimate. The harness ships no price list, because one in code goes stale. Supply
prices per run as USD per million tokens:

```bash
export CONTRACT_EVAL_USD_PER_MTOK_INPUT=3.00
export CONTRACT_EVAL_USD_PER_MTOK_OUTPUT=15.00
```

`cost` then carries the estimate together with the prices and token counts it was
computed from, so it can be recomputed from the capture alone. It is `null` when either
price is unset or the provider reported no token counts (the stub and the command
adapter report none). Captures written before these fields existed omit them, and their
integrity digests verify unchanged.

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

