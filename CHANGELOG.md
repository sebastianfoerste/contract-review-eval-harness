# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The Python package version for v0.7.0-rc1 is `0.7.0rc1` (PEP 440).

## [Unreleased]

### Added

- The wheel ships byte-identical copies of `data/`, `expected/`, `fixtures/`, the v1 robustness campaign and the annotation drafts. `contract_eval.paths` looks in the working directory first, then an editable checkout, then the bundled copy. An install with no checkout reproduces the committed certificate byte for byte.
- CI adds a Python 3.11/3.12 job and a wheel job that installs the built wheel into a clean environment and runs a case outside the checkout.
- Python API in `contract_eval.api`. `score_review` and its alias helpers move there, joined by `load_case`, `evaluate_review`, the `Verdict` enum and a sealed result payload. The package exports them.
- Pytest plugin `contract_eval.pytest_plugin`, registered under `pytest11`. It provides `assert_review_passes` (release or regression policy), a `contract_case` fixture and an end-of-run summary. `examples/test_my_reviewer.py` is a copyable example.
- Reference evidence chain: immutable second-annotation intake, written adjudication and an atomic reference freeze (`reference-import`, `reference-prepare`, `reference-freeze`, `reference-status`). Evaluation refuses a v3 decision until the chain is final. (#32)
- Canonical web export and `make web-check`, which hold `contract-eval-web` to the committed harness inputs. CI pins 30 scoring vectors in `examples/web-parity-vectors.json` and fails when they no longer reproduce byte for byte. (#32, #36)
- German NDA and SPA candidate cases, pending gold answers. (#33)
- Matter evaluation: several documents read for one client, scored on conflicts, positions and escalations with every citation bound to the document it quotes, under conditions that differ in the documents a system may see and in the prompt that introduces them. Each issue is assigned to a development or an evaluation split when it is written, and an experiment log labels a result that is not held out. The first matter, `matters/northwind-saas/`, reuses the three certified contracts and has single-annotator draft answers. The commands sit under `contract-eval dev`, CI verifies the matter hashes, answer offsets and manifests, and `make matter-demo` scores a toy matter. The matter path runs from a checkout: the wheel does not ship `matters/`. See `docs/MATTER_EVALUATION.md`.
- An offsets helper (`offsets.py`) inside the annotation pack. It reports a quote that matches more than once as ambiguous and a quote that matches nothing as absent. (#29)
- A test that keeps the version at a release candidate until the second annotation returns. A final version also requires a disagreement ledger per case. (#31)
- `contract-eval score`: score any tool's plain review JSON against a bundled case or your own `--contract` and `--gold`. It prints the scorecard with the release decision first and exits 1 on `REJECT`, 2 on unreadable input; `--fail-on human-review` tightens the gate. A result on your own answer set is comparison-only and ineligible for certification. `docs/score-your-own-tool.md` explains the workflow.
- JSON Schemas for a review and an answer set in `schemas/`, generated from the models by `scripts/export_schemas.py`. CI rejects drift.
- A composite GitHub Action (`action.yml`) that runs `contract-eval score` on a repository's review files, writes the scorecards to the job summary and fails on `REJECT`. CI runs it against the NDA stub. See `docs/ci.md` and `examples/ci/contract-eval.yml`.
- `--adapter stub|anthropic|openai-compatible|command`. The OpenAI-compatible adapter reaches any Chat Completions endpoint through a configurable base URL; the command adapter runs any program that reads the contract on stdin and prints review JSON. `--live` stays an alias for `--adapter anthropic`.
- Captures record the adapter call's latency and, when `CONTRACT_EVAL_USD_PER_MTOK_INPUT` and `_OUTPUT` are set, a cost estimate with the prices it assumed. Both fields are omitted while unset, so existing captures keep their bytes and digests.
- `scripts/build_leaderboard.py` re-scores every committed review output and writes `examples/leaderboard.md` and `.json`; CI rejects drift.
- `scripts/build_site.py` renders the scorecard, certificate, live run and leaderboard into a static site, and `.github/workflows/pages.yml` deploys it once the `PAGES_ENABLED` repository variable is `true`. The site is published at <https://sebastianfoerste.github.io/contract-review-eval-harness/> and linked from the README.
- `examples/quickstart.ipynb`, a notebook that opens in Colab.
- `docs/metrics.md`: one section per scorecard row with its formula, denominator, edge cases and whether the row can block a release.
- A "How this compares" section in the README.
- GitHub issue forms and a pull request template.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) and `CITATION.cff`.
- This changelog.
- `tests/test_docs.py`, an offline check of relative doc links, metric sections and issue forms.

### Changed

- `requires-python` is now `>=3.11`. 0.7.0rc1 required 3.12.
- Maintainer commands (`reference-*`, `verify-*`, `evaluate-obligations`) move under `contract-eval dev`. They stay accepted, unlisted, at the top level, so Make targets, CI steps and docs keep working. `cli.py` re-exports the functions that moved to `contract_eval.api`, so existing imports keep working.
- Schema v1 is an input format, not a parallel system. `contract_eval.upgrade` converts v1 reviews and gold sets to v2, so legacy captures can enter the evidence-bound path. The committed `fixtures/*_stub.v2.json` files are removed; the stub adapter upgrades its v1 fixture on load. (#26)
- Both annotators are named, with their agreement, from one registry in `contract_eval.annotators`. (#27)
- The README leads with what the harness does and is rewritten for clarity. (#37, #42)
- `CONTRIBUTING.md` is rewritten around three paths: add a case, add an adapter, volunteer as an annotator.
- `make demo` also prints the scorecard it writes. `docs/demo.png` is a real rendering of that output and replaces a mock image. (#41)

### Removed

- `CLAUDE.md`, which held only generic skill routing; `AGENTS.md` keeps the repository guidance. (#41)
- The weekly traffic snapshot workflow (`.github/workflows/traffic.yml`) added in 0.3.0. (#41)
- The stale, unreferenced `docs/scorecard.svg`. (#41)
- The tracked `history/run_*.json` files. Every evaluate run writes one, so they stay ignored, as does the root `run-provenance.json`. (#41)

### Fixed

- The v2 evaluation path was not connected in 0.7.0rc1: no adapter produced an evidence-linked review and no CLI command consumed one. Both adapters gain `review_v2`, and `evaluate-obligations` runs a contract to an evidence-bound score, recording policy v3's refusal instead of a release decision. (#25)
- A set-precedence bug in campaign validation: `a | b - known_ids` parsed as `a | (b - known_ids)`. (#25)
- The annotation template's commercial perspective described the migration instead of the review's standpoint. (#28)
- Exported feedback items state `origin {"kind": "synthetic_fixture"}`, which the dashboard's feedback schema requires. (#34)
- The NDA severity rationales for `term`, `permitted_disclosure`, `definition` and `notices` argue from the Disclosing Party's side, which the answer set's `review_context` names, and the case study no longer calls all three gold sets receiving-side reviews. The four rationales were drafted with AI assistance and await the maintainer's adoption. Severities, flags and scores are unchanged. (#41)
- Documented figures match the harness output: severity accuracy (0.57 to 0.60 across the cases) replaces legacy risk-flag accuracy as the headline risk figure, and the NDA's clause precision is 0.92, not 0.83. (#41)
- The README links the public `contract-eval-web` repository, which has no hosted demo. (#41)

## [0.7.0-rc1] - 2026-09-03

This release candidate does not mark the benchmark as validated. The gold sets remain single-annotator candidates, policy v3 refuses to certify them, and `expected/*.json` under schema v1 is still authoritative.

### Added

- Gold schema v2. Obligations are located by raw source offsets (zero-based character indices, half-open ends), with a normalized-to-raw index. Migration yields 33 candidate obligations from the 32 v1 concepts; the composite DPA breach and DPIA clause is split in two. The candidates are not authoritative. (#19)
- Blind annotation pack with the contracts, the review context, an annotator guideline and empty templates. `make annotation-bundle` exports it as a standalone archive, and `annotations/README.md` discloses that blindness is procedural, not technical. (#19, #23)
- Review output v2. Citations carry ids and findings list the citation ids that support them. A finding binds to an obligation by raw span overlap only when all its evidence resolves to the same one; an unbound finding earns nothing. (#21)
- Policy v3 and certificate v4. `evaluate_v3` raises `GoldNotAdjudicated` for any gold set that is not frozen and adjudicated, so v3 certifies nothing yet. (#21)
- Blind annotation comparison and disagreement ledger. Obligations are matched by span overlap, disagreements are recorded by kind, and the return's hash is frozen before comparing. Weighted kappa is reported as not defined on degenerate samples. (#22)
- Campaign v2: 75 generated adversarial scenarios keyed to obligation ids and addressed by raw offsets, covering all 33 candidate obligations. It is a candidate; campaign v1 stays the campaign the release certificate carries. (#24)
- Reasoning effort is pinned per run, set with `CONTRACT_EVAL_EFFORT`, and recorded in captures and replay provenance. (#20)
- Offline tests for the live adapter contract.

### Changed

- The live adapter constrains output with the response schema (`messages.parse` with `output_format=ReviewOutput`) instead of slicing JSON out of prose. The clause naming convention and verbatim quoting move into the schema's field descriptions. `max_tokens` rises to 16000 and `PROMPT_VERSION` becomes v2.
- The package version is `0.7.0rc1`, so captures and replay provenance record a matching `scorer_version`.

## [0.6.0] - 2026-09-02

### Added

- Every adapter attempt is recorded as a `CapturedReview` before it is parsed: source and gold snapshots, the sanitized request, the raw response and the parsed output, each hashed, under one canonical integrity digest. The capture is written before the provider is called, and a failed write aborts the attempt. (#18)
- Eight capture states. Truncated, malformed, interrupted, provider-error and configuration-error attempts leave evidence and are never scored; only a completed capture reaches the scorer.
- `score-output` re-scores captured bytes with no network access. Current-input drift fails by default; `--allow-input-drift` reproduces the historical result and marks it comparison-only and ineligible for certification.
- The three preserved 2026-09-01 raw outputs are imported as legacy captures with origin `legacy_file`. Fields that run never recorded stay null.
- The live-run report is generated from captures against a versioned replay specification. A CI check fails on any drift from a fresh generation.

### Changed

- `score_review` is a pure function over source text, gold set and output, so live evaluation and offline replay run identical code. `Adapter.review` is a thin wrapper over capture.
- The Anthropic client uses `max_retries=0` and an explicit timeout, so one attempt equals one provider request. Requested and returned model identifiers are recorded separately.
- Captures are written through a temporary file that is flushed, fsynced and moved into place with `os.replace`.

## [0.5.2] - 2026-09-02

### Fixed

- The certificate did not publish the inputs policy v2 decides on (risk precision, risk recall, severity accuracy, duplicate and conflicting flags) and advertised a `risk_flag_accuracy_target` that no longer decided anything. Certificate schema v3 corrects the artifact shape; policy semantics are unchanged. (#17)

### Changed

- Nine requirements live in one typed registry (stable ID, metric key, comparator, threshold, failure class, failure code, description). It drives the case decision, the published policy metadata, the per-case scores and the verifier's markdown.
- A missing decision input raises instead of defaulting.
- Diagnostics, including legacy risk-flag accuracy, are published in a separate labelled table. A test shows they cannot move a decision.
- Verification publishes `verification_scope`. A frozen copy of the v2 builder reproduces v2 certificates under the rules they were issued with. Input drift downgrades a v2 result to `integrity_only` and names the drifted inputs. v1 stays integrity only, and an unknown schema fails closed.
- The committed campaign report is regenerated because it embeds the baseline certificate.

## [0.5.1] - 2026-09-01

### Added

- Release policy v2. Risk precision, risk recall, severity accuracy, and duplicate and conflicting flags enter the eligibility decision. Twenty spurious high-risk findings previously left a case pilot eligible. (#16)
- The verifier dispatches by certificate schema. A v1 certificate is verified for integrity on its original policy and is not re-decided; an unrecognised schema fails closed. (#16)

### Changed

- Empty-set semantics for risk metrics are defined. Both sets empty scores 1.0; predictions with nothing expected score precision 0.0 and recall 1.0; expected risks with nothing predicted score precision 1.0 and recall 0.0. Previously every empty case returned 0.0. (#16)
- Metric shortfalls route to human review instead of automatic rejection. Citation failures remain hard blockers. (#16)
- `demo-regression-policy.v2` (regression against the bundled fixture) and the release certificate (eligibility) are named and documented as separate gates. (#16)
- Legacy `risk_flag_accuracy` stays in scorecards, labelled legacy and excluded from release decisions. (#16)

### Fixed

- Rationale parity was checked only when `severity_rationale` was non-empty, so a gold set with unjustified risk flags validated. It is now checked unconditionally, and blank rationales are rejected. (#15)
- When two labels collapsed onto the same clause, the last risk flag silently won. Duplicates are now reported, a duplicate with a different severity is reported as a conflict, and the first prediction wins. (#15)

## [0.5.0] - 2026-09-01

### Added

- Clause coverage by source span. Each clause type carries a verbatim anchor and owns the region up to the next anchor; it counts as covered when a grounded citation falls inside that region. Labels never enter the comparison. Span coverage measures citation placement, not comprehension, and is reported beside the label-based scores. (#14)
- `make anchor-check` and a CI step fail the build when an anchor matches zero places or more than one. (#14)
- Gold sets state whose review they encode: party, governing law, objective and risk appetite. All three are conservative reviews for Northwind Materials GmbH under German law, with the GDPR also governing the DPA and the data-protection points of the SaaS agreement: as Disclosing Party to the NDA, as Customer under the SaaS agreement and as Controller under the DPA. (#14)

### Changed

- The traffic snapshot docs recommend a least-privilege fine-grained token instead of a classic token with the `repo` scope.

## [0.4.1] - 2026-09-01

### Added

- Risk precision, recall and F1 over identification, severity accuracy on jointly identified risks, and a severity confusion count. Risk accuracy alone was blind to false positives. (#13)
- `run-provenance.json`, which records generation and scoring times separately, the scorer version, and digests of gold sets and source contracts. (#13)

### Changed

- The live adapter defaults to `claude-opus-5`.
- The 2026-08-28 live comparison is retracted: it compared two separate generations and its raw output was not preserved. A controlled experiment replaces it, scoring one captured, hashed output with aliasing off and on. (#13)
- Aliasing is documented as a known limitation (recall reaches at most 0.818 and the map does not transfer between runs), with source-span anchoring as the migration path. (#13)

### Fixed

- `_severity_rationale` was silently discarded, so rationales were never validated. `ExpectedAnswer` now forbids unknown fields, types `risk_flags` as `Severity` and requires exactly one rationale per flag. (#13)
- Citation grounding accepted reordered or partly substituted quotes (unordered token sets at 85 percent overlap). It now requires an exact contiguous span of the normalised source and returns the span offsets. (#13)
- The live adapter capped responses at 2000 tokens, which truncated full reviews into invalid JSON. The cap is raised and configurable, and truncation raises an explicit error. (#13)

## [0.4.0] - 2026-08-31

### Added

- `clause_aliases` in gold sets map a synonym onto the gold set's own name for the same clause. A test asserts every alias targets a declared clause type and none shadows a canonical name. (#12)
- The dated live run `examples/live-run-claude-opus-4-8-2026-08-28.md`, with scores before and after aliasing. Its comparison was retracted in 0.4.1. (#12)
- A severity rationale for every risk flag in each gold set. (#11)
- `docs/ANNOTATION_GUIDELINE.md`: clause naming, severity calibration, why every stub carries exactly one fabricated citation, and why a fixture is never tuned to clear a threshold. (#10)

### Changed

- The NDA and SaaS agreements gain six clauses each, with deliberate defects. Coverage grows from ten clause types to thirty-two. (#11)
- The case study covers three agreement types, the adversarial campaign and the DPA result. (#10)

### Fixed

- Clause types were compared by string equality, so a correct review using other labels scored as a failure. On the DPA case a live run went from 0.40 to 1.00 clause F1 and from 0.00 to 1.00 risk accuracy. (#12)

## [0.3.0] - 2026-08-28

### Added

- Art. 28(3) GDPR data processing agreements as a third contract type: a synthetic agreement, a gold answer across lit. a to h plus Chapter V transfers, a stub fixture and six adversarial scenarios. (#9)
- The live adapter model is selectable with `--model` or `CONTRACT_EVAL_MODEL`. (#9)
- A CI workflow that writes a weekly repository traffic snapshot to an orphan `traffic-stats` branch. Views and clones are null until a `TRAFFIC_TOKEN` secret is present.

### Changed

- The case set lives in `contract_eval.cases.ALL_CASES`; no consumer hardcodes it. (#9)
- The campaign validator requires a semantic control for every case it covers and rejects an unknown `base_case`. (#9)

## [0.2.0] - 2026-08-28

The package version in `pyproject.toml` was not bumped for this tag and still reads `0.1.0`.

### Added

- Benchmark release certificates, verified end to end. (#7)
- An adversarial contract robustness lab with a committed campaign and report. (#7)
- CI gates for the release certificate and the robustness campaign. Certificate tampering, benchmark drift and robustness-report drift fail the build. (#7)
- A verification manifest (`verification-manifest.v1`) that records the release certificate and robustness campaign as verification artifacts and validation commands. It replaces the `portfolio-proof.v1` contract and drops its hiring-oriented metadata. (#8)

### Changed

- Relicensed under MIT.

## [0.1.0] - 2026-07-02

### Added

- The `contract-eval` package, scaffolded with uv, with Pydantic models for review output and expected answers.
- Synthetic NDA and SaaS agreements, each with expected answers and a stub fixture.
- A stub adapter and an optional live adapter. The live adapter ships as an optional extra with a reproducible demo-live path.
- A scorer with clause, risk, citation and hallucination metrics.
- An `evaluate` CLI and a scorecard renderer.
- A case study, and README sections on human judgment and known limitations, with diagrams.
- A live frontier-model scorecard snapshot.

[Unreleased]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.7.0-rc1...HEAD
[0.7.0-rc1]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.6.0...v0.7.0-rc1
[0.6.0]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.5.2...v0.6.0
[0.5.2]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/sebastianfoerste/contract-review-eval-harness/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sebastianfoerste/contract-review-eval-harness/releases/tag/v0.1.0
