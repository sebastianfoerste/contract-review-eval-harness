# Privacy

This harness processes no personal data and no client data.

- Every contract under `data/` is synthetic and invented for evaluation. Party names are fictional.
- The default offline path transmits nothing. The deterministic stub reads bundled fixtures only.
- If you opt into `--live`, the synthetic contract text is sent to the Anthropic API to generate review output. Do not point `--live` at real or confidential contracts.

The harness is built around an explicit human-review gate: it measures and reports on AI
review quality so a qualified lawyer can decide what to rely on. It never stands in for
legal advice.

## What each adapter sends, and where

The adapter is chosen with `--adapter`; `--live` is an alias for `--adapter anthropic`,
and the default is `stub`.

- **`stub`** (default): nothing leaves the machine. The adapter reads
  `fixtures/<case>_stub.json` and makes no network call.
- **`anthropic`** (`--live`): the contract text goes to the Anthropic API inside the
  prompt, through the Anthropic SDK. The key is read from `ANTHROPIC_API_KEY`; if that
  variable is unset, the adapter reads it from a `.env` file three directories above
  the installed package when one exists: the repository root in a checkout or an
  editable install, the environment's `lib/pythonX.Y` directory in a wheel install. A
  run never logs, stores or writes the key into a capture.
- **`openai-compatible`**: the contract text goes inside the prompt to
  `<base URL>/chat/completions`. The base URL is `--base-url`, else `OPENAI_BASE_URL`,
  else `https://api.openai.com/v1`. The key is read from the environment variable
  named by `--api-key-env` (default `OPENAI_API_KEY`) and sent as a bearer token; only
  the variable's name is held, never the key. Redirects are refused, so the key is not
  forwarded to a host the response names. Do not use a plain `http://` base URL for any
  host other than localhost: the key and the contract would travel unencrypted.
- **`command`**: the contract text is piped to your program's standard input, and the
  program inherits the caller's full environment, including any API keys set in it,
  plus `CONTRACT_EVAL_CASE`. The harness itself sends nothing further; a wrapper that
  calls a remote service sends the contract wherever it sends it. The command line is
  recorded in the run's provenance, so it must not carry secrets.

## The GitHub Action and the playground

- **GitHub Action**: scores review files on your own runner. It installs the package
  from the action's checkout, passes its inputs to the scorer as environment variables
  and writes the scorecards to the job summary and to the `out` directory on that
  runner. It calls no model and sends nothing to this project.
- **Playground**: scores in your browser. On first use the page loads the Pyodide
  runtime, with its `micropip` and `pydantic` packages, from the jsDelivr CDN
  (`cdn.jsdelivr.net/pyodide`), and the package wheel, the `score.py` bridge and the
  example reviews (`samples.json`) from the results site itself. The pasted review is
  handed to a web worker in the same tab and is not uploaded anywhere.
