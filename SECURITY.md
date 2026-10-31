# Security

An evaluation harness for AI contract review, built on synthetic contracts. This page
says what ships and where it runs, which versions receive fixes, what the default path
does, and how to report a problem.

## What ships and where it runs

- **The Python package and wheel** (`contract-eval`): the command line, the Python API
  and the pytest plugin. They run on your machine. The package is not on PyPI; it is
  installed from this repository or from a wheel built with `uv build`.
- **The composite GitHub Action** (`action.yml`): runs inside other repositories' CI.
  It installs the package from the action's own checkout into a virtual environment on
  the caller's runner and scores the named review files there. Inputs reach the scorer
  as environment variables, never as interpolated shell text. It sends nothing to this
  project.
- **The browser playground** on the results site: a web worker loads the Pyodide
  runtime from the jsDelivr CDN and the package wheel from the site, then scores a
  pasted review inside the browser. The review is not uploaded.
- **The adapters** that turn a contract into a review. `stub` (the default) reads
  bundled fixtures. `anthropic` (`--live`) sends the contract text to the Anthropic API.
  `openai-compatible` sends it to the configured base URL, `https://api.openai.com/v1`
  unless overridden. `command` pipes it to a local program of your choice, which also
  inherits the caller's environment. [PRIVACY.md](PRIVACY.md) lists what each adapter
  sends and where.

## Default path

The default path makes no network call to a model provider and needs no API key: the
deterministic stub adapter is scored against bundled fixtures. All contracts under
`data/` are fabricated; no real agreement or client data is processed. The Anthropic
SDK is an optional, lazily imported dependency, so the default path never imports it.

## Supported versions

| Version | Supported |
|---|---|
| `main` | yes |
| v0.6.0, the latest release at the time of writing | yes |
| v0.7.0-rc1, a pre-release of 2026-09-03 | fixes land on `main`, not on the release candidate |
| earlier releases | no |

The GitHub Action exists only on `main` so far: no release tag contains `action.yml`.
Pin it to a full commit SHA as [docs/ci.md](docs/ci.md) shows, and update the SHA
deliberately.

## Reporting a vulnerability

Report it through the repository's Security tab, "Report a vulnerability":
<https://github.com/sebastianfoerste/contract-review-eval-harness/security/advisories/new>.
Private vulnerability reporting is enabled, so the report and any exploit details are
visible only to you and the owner until a fix is published. Name the affected
component (package, Action, playground or an adapter) and the version or commit. Leave
live credentials out even there; a redacted example is enough. Do not open a public
issue for an exploitable problem. A dependency advisory with no exploit can still be
reported as an ordinary issue.
