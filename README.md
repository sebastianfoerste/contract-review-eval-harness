# contract-review-eval-harness

[![CI](https://github.com/sebastianfoerste/contract-review-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/sebastianfoerste/contract-review-eval-harness/actions/workflows/ci.yml)

See [CASE_STUDY.md](CASE_STUDY.md) for the problem, controls, and limitations.

Evaluation harness for legal AI contract review: clause scoring, citation grounding and hallucination counts against a gold answer set. Not legal advice; data is synthetic.

**Public-safety posture:** synthetic contracts only, visible source provenance in every citation check, an explicit human review gate before reliance, and no legal advice.
Verification manifest: [`docs/verification-manifest.json`](docs/verification-manifest.json).

![demo](docs/demo.png)

## Run it

```bash
git clone https://github.com/sebastianfoerste/contract-review-eval-harness
cd contract-review-eval-harness
make install && make test
make demo
```

Runs end to end, offline and deterministically.

## What the demo produces

The demo writes a scorecard with clause-level scoring, citation-grounding assessment and unsupported-citation detection. In the sample run, the harness catches a fabricated citation and marks the output for rejection. You can read the committed sample output in [`examples/scorecard.md`](examples/scorecard.md) and [`examples/scorecard.json`](examples/scorecard.json).

The [release certificate](examples/release-certificate.md) evaluates all bundled
cases under a stricter legal-review policy. It hashes the source contract, gold
answer, and adapter output for each case, rejects any unsupported citation, and
binds the suite decision to a reproducible integrity digest. `make
certificate-verify` re-runs the offline adapter, recomputes every score and input
digest, and fails on certificate tampering or benchmark drift.

The [Adversarial Contract Robustness Lab](examples/adversarial-robustness-report.md)
adds eighteen deterministic minimal-pair scenarios across the NDA, SaaS and DPA
fixtures: party-definition changes, residual-knowledge carve-outs, duration changes,
conflicting governing law, instruction injection, uptime negation, model-training
rights, liability-cap changes, renewal windows, missing schedules, processing-instruction
carve-outs, discretionary confidentiality, extended breach windows, and one
semantic-preserving control per contract type. The
[local HTML campaign view](examples/adversarial-robustness-report.html) exposes
critical recall, severity-weighted sensitivity, false reassurance, required
abstention, citation grounding, injection resilience, repeated-run consistency,
and every scenario-level failure.

The campaign design follows current evidence that apparently strong aggregate
scores can conceal subtle legal failures. [ContractEval](https://arxiv.org/abs/2508.03080)
reports material differences across contract-review tasks and model settings.
[Better Call CLAUSE](https://arxiv.org/abs/2511.00340) stress-tests nuanced and
adversarial contract flaws. [LegalCiteBench](https://arxiv.org/abs/2605.10186)
documents persistent weaknesses in exact legal citation tasks. The committed
offline report therefore preserves the adapter's failures and carries forward the
baseline release-certificate rejection.

```markdown
# Contract Review Eval Scorecard: nda

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.83 | predicted clause types that were expected |
| Clause recall | 1.00 | expected clause types that were found |
| Clause F1 | 0.91 | harmonic mean of precision and recall |
| Risk-flag accuracy | 0.50 | risky clauses flagged at the expected severity |
| Citation grounding | 0.80 | 4/5 quotes grounded in the source |
| Hallucination count | 1 | cited quotes not grounded in the source |
```

## What it checks

- Clause precision and recall.
- Risk-flag accuracy.
- Citation grounding.
- Unsupported or fabricated citations.
- Input drift and suite-level release eligibility.
- Adversarial and subtle contract changes.
- Critical false reassurance and required abstention.
- Instruction-injection and semantic-invariance behavior.
- Repeated-run consistency and input-bound robustness verification.

## Problem

"The AI reviews contracts" is a demo, not a claim a serious reviewer can rely on. The useful question is: how do you know the review is any good? This harness scores AI review output against an expected answer set and counts the failures that matter most in legal work.

## Verified behavior

- Quality is measured, not asserted.
- Unsupported citations are treated as first-class failures.
- The scorecard ends with human-review instructions.
- The default path is offline and deterministic, so the demo runs with no API key.

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
`claude-opus-4-8`.

```bash
uv run python -m contract_eval evaluate --case all --live --model claude-opus-4-8
```

A captured run against a frontier model is committed in the examples folder as a dated snapshot. Live output is non-deterministic; the committed file is not a stable benchmark. Any published comparison must name the model, the date and the harness version, because a score without those three is not reproducible.

## Use cases

- NDA: confidentiality, definition, term, return/destruction, governing law.
- SaaS agreement: service levels, data protection, limitation of liability, term, auto-renewal.
- Data processing agreement: Art. 28(3) lit. a to h GDPR, Chapter V transfers, governing law.

The DPA case is where clause coverage and legal judgment come apart most clearly.
The offline adapter scores 0.95 clause F1 on it — it finds every clause — while
rating the exclusion of on-site inspections as low risk and a transfer clause
carrying no Chapter V mechanism as low risk. Both are material Art. 28(3) and
Chapter V defects. A reviewer reading only the coverage number would not see them.

Adding a fourth contract type means adding four files and one entry in
[`src/contract_eval/cases.py`](src/contract_eval/cases.py); no consumer hardcodes
the case set. The [annotation guideline](docs/ANNOTATION_GUIDELINE.md) records how
clause types are chosen, how severities are calibrated, and why a stub fixture is
never tuned to clear a threshold.

## Synthetic data statement

Every contract under `data/` is synthetic and fabricated for evaluation. No real agreement, client, or personal data is included.

## Limitations

This is a public-safe prototype and a human-review evaluation artifact. The answer
sets and the eighteen perturbations are synthetic and intentionally bounded to
three contract types. Pilot eligibility from either certificate still requires
legal, security, privacy, and product review. It never authorizes autonomous
contract reliance.

## Stack

Python, Pydantic, pytest and uv. The optional live adapter is behind a flag and the default offline path does not need an API key.

## Human-authored legal judgment

AI tools assisted the implementation, but the parts that carry the value are human-authored: the gold answer sets, risk taxonomy, clause types and citation-grounding rules. The point of this repository is not code volume; it is showing how legal judgment can be made structured, testable and reviewable.
