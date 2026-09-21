# Project Architecture: Engine & Interactive Explorer

This project consists of two synchronized repositories designed to fulfill distinct roles within the legal AI contract evaluation lifecycle.

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
                  |   - OpenAI Sites continuous hosting              |
                  +--------------------------------------------------+
```

---

## Repository Breakdown

| Dimension | `contract-review-eval-harness` | `contract-eval-web` |
|---|---|---|
| **Role** | Evaluation Engine & Ground Truth | Interactive Evidence Lab & Public Explorer |
| **Language & Runtime** | Python 3.13 (uv, Pydantic, pytest) | TypeScript (React 19, Next.js 16, Vinext) |
| **Hosting & CI** | GitHub Actions / local CLI | OpenAI Sites / Cloudflare Workers |
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
   - `make web-check`: Embedded directly in the harness's standard `make check` target.
   - `contract-eval-web/tests/scoring.test.mjs`: Node test suite that runs 32 tests verifying TypeScript scoring against the exported Python vectors.

---

## Why Separate Repositories?

1. **Independent Hosting Lifecycle**: `contract-eval-web` is managed as an OpenAI Sites repository with Cloudflare Worker builds (`.openai/hosting.json`, `build/sites-vite-plugin.ts`, `.sites-runtime`). Merging directories into a mono-tree risks breaking Sites deploy automation.
2. **Distinct Security & Dependency Profiles**: The Python harness requires zero JavaScript dependencies and is completely deterministic and air-gapped by default. The web explorer requires Node.js tooling and modern web dependencies.
3. **Focused Development**: Methodology, annotation adjudication, and model adapters evolve in the harness; UI/UX, visualization, and inspection features evolve in the web app.

---

## Future Monorepo Re-evaluation Criteria

A physical repository merge may be reconsidered in the future under the following conditions:
1. **Sites Multi-Directory Support**: When OpenAI Sites explicitly supports repository subfolder configurations (e.g. configuring `apps/web` as the root) without breaking deployment triggers.
2. **Coupled Adjudication Upgrades**: When the v2 second-annotator adjudication lands and the web UI requires continuous, simultaneous updates to visualize atomic obligation graphs and evidence spans.
3. **Unified Monorepo Tooling**: When a single unified task runner (e.g. Turborepo or root Makefile) can coordinate both Python uv venv and Node environments in a single unified CI pipeline.
