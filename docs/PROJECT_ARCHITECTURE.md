# Project Architecture: Engine & Interactive Explorer

This project consists of two synchronized repositories designed to fulfill distinct roles within the legal AI contract evaluation lifecycle.

Both repositories are public. [`contract-eval-web`](https://github.com/sebastianfoerste/contract-eval-web) is deployed to Cloudflare Workers from its `main` branch, as its README describes; the README names no public URL.

```
                  +--------------------------------------------------+
                  |           Evaluation Engine & Source of Truth    |
                  |             (contract-review-eval-harness)       |
                  |                                                  |
                  |   - Authoritative Python scoring (score_review)  |
                  |   - Synthetic contracts, gold answers & fixtures |
                  |   - Live model adapters & captured responses     |
                  |   - Release certification & adversarial tests    |
                  |   - Ground-truth v2 evidence-binding pipeline    |
                  +-------------------------+------------------------+
                                            |
                                            | export-benchmark.py
                                            | (cases, hashes, parity vectors)
                                            v
                  +--------------------------------------------------+
                  |           Interactive Evidence Lab               |
                  |               (contract-eval-web)                |
                  |                                                  |
                  |   - Zero-dependency client/edge scoring engine   |
                  |   - Next.js 16 / Vinext / React 19 / Cloudflare  |
                  |   - Interactive scenario toggling & comparisons  |
                  |   - In-memory session tracking & report exports  |
                  |   - Workers Builds deploys every push to main    |
                  +--------------------------------------------------+
```

---

## Repository Breakdown

| Dimension | `contract-review-eval-harness` | `contract-eval-web` |
|---|---|---|
| **Role** | Evaluation Engine & Ground Truth | Interactive Evidence Lab & Public Explorer |
| **Language & Runtime** | Python 3.11+ (uv, Pydantic, pytest) | TypeScript (React 19, Next.js 16, Vinext) |
| **Hosting & CI** | GitHub Actions / local CLI | Cloudflare Workers (Workers Builds deploys every push to `main`) / GitHub Actions on pull requests |
| **Authoritative Logic** | Definitive scoring, policy certification, v2 obligations | Deterministic browser-safe port of `score_review` |
| **Data Access** | Offline synthetic contracts + optional `--live` adapters | Read-only static snapshot (`lib/benchmark.json`) |
| **Integrity Checks** | SHA-256 bound certificates, robustness hashes, release hold | 32 automated parity tests against Python outputs |

---

## How They Connect & Synchronize

1. **Asset & Parity Export**:
   `contract-eval-web/scripts/export-benchmark.py` reads the harness's synthetic contracts (`data/`), reference gold sets (`expected/`), and sample reviews (`fixtures/`). It executes Python `score_review` across multiple scenarios and alias configurations, writing:
   - `contract-eval-web/lib/benchmark.json`: Contract texts, expected answers, stub reviews, source commit, and cryptographic file hashes.
   - `contract-eval-web/tests/python-parity.json`: 30 scoring vectors calculated by Python.

2. **Automated Parity Verification**:
   - `contract-review-eval-harness/scripts/check_web_sync.py`: Verifies that `contract-eval-web` hashes match the harness, validates version alignment (`0.7.0rc1`), and re-evaluates all parity vectors.
   - `make web-check`: Embedded directly in the harness's standard `make check` target. It needs the web repository checked out next to the harness, so it does not run in GitHub Actions.
   - `contract-review-eval-harness/scripts/check_parity_vectors.py` (`make parity-check`): Runs in GitHub Actions. It fails when the committed `examples/web-parity-vectors.json` no longer reproduces byte-for-byte from the current scorer, which makes every scoring change a reviewed diff and the cue to re-export the web app.
   - `contract-eval-web/tests/scoring.test.mjs`: Node test suite that runs 32 tests verifying TypeScript scoring against the exported Python vectors.

---

## Why Separate Repositories?

1. **Independent Hosting Lifecycle**: Cloudflare Workers Builds is connected to the `contract-eval-web` repository and deploys every push to its `main`, running `npm run build` and then `npx wrangler deploy` from the repository root; GitHub Actions runs lint, types, tests, the build and a local Worker API check on each pull request first. Merging directories into a mono-tree would move the app out of the root its build and deploy expect, and, as set up now, every harness push to `main` would also deploy the web app.
2. **Distinct Security & Dependency Profiles**: The Python harness requires zero JavaScript dependencies and is completely deterministic and air-gapped by default. The web explorer requires Node.js tooling and modern web dependencies.
3. **Focused Development**: Methodology, annotation adjudication, and model adapters evolve in the harness; UI/UX, visualization, and inspection features evolve in the web app.

---

## Future Monorepo Re-evaluation Criteria

A physical repository merge may be reconsidered in the future under the following conditions:
1. **Subfolder Deployment**: When the web app's build and deploy (`npm run build`, then `npx wrangler deploy`) are shown to work from a repository subfolder (e.g. `apps/web`) without a harness-only push to `main` deploying the app.
2. **Coupled Adjudication Upgrades**: When the v2 second-annotator adjudication lands and the web UI requires continuous, simultaneous updates to visualize atomic obligation graphs and evidence spans.
3. **Unified Monorepo Tooling**: When a single unified task runner (e.g. Turborepo or root Makefile) can coordinate both Python uv venv and Node environments in a single unified CI pipeline.
