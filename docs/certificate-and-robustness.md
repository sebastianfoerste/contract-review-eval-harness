# Release certificate, gates and robustness lab

Moved from the README. See also the [release certificate](../examples/release-certificate.md) and the [robustness report](../examples/adversarial-robustness-report.md).

## What the demo produces

The demo writes a scorecard with clause-level scoring, citation-grounding assessment and unsupported-citation detection. In the sample run, the scorecard reports one fabricated citation and says it must be rejected; the release certificate below rejects the NDA output on that ground. You can read the committed sample output in [`examples/scorecard.md`](../examples/scorecard.md) and [`examples/scorecard.json`](../examples/scorecard.json).

The [release certificate](../examples/release-certificate.md) evaluates all bundled
cases under a stricter legal-review policy. It hashes the source contract, gold
answer, and adapter output for each case, rejects any unsupported citation, and
binds the suite decision to a reproducible integrity digest. `make
certificate-verify` re-runs the offline adapter, recomputes every score and input
digest, and fails on certificate tampering or benchmark drift.

The [Adversarial Contract Robustness Lab](../examples/adversarial-robustness-report.md)
adds eighteen deterministic minimal-pair scenarios across the NDA, SaaS and DPA
fixtures: party-definition changes, residual-knowledge carve-outs, duration changes,
conflicting governing law, instruction injection, uptime negation, model-training
rights, liability-cap changes, renewal windows, missing schedules, processing-instruction
carve-outs, discretionary confidentiality, extended breach windows, and one
semantic-preserving control per contract type. The
[local HTML campaign view](../examples/adversarial-robustness-report.html) exposes
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

## Scores

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.92 | predicted clause types that were expected |
| Clause recall | 1.00 | expected clause types that were found |
| Clause F1 | 0.96 | harmonic mean of precision and recall |
| Risk precision | 0.83 | flagged clauses that the gold set treats as risks |
| Risk recall | 0.83 | gold risks the review flagged |
| Risk F1 | 0.83 | harmonic mean of risk precision and recall |
| Severity accuracy | 0.60 | correct severity among jointly identified risks |
| Risk false positives | 1 | clauses flagged that the gold set does not treat as risks |
| Risk missed | 1 | gold risks the review did not flag |
| Duplicate / conflicting flags | 0 / 0 | predictions collapsing onto one clause |
| Risk flags without evidence | 0 | flagged clauses with no grounded citation inside them |
| Span coverage | 0.73 | gold clauses with a grounded citation inside them |
| Citation grounding | 0.89 | 8/9 quotes matched as an exact span of the normalised source |
| Hallucination count | 1 | cited quotes not grounded in the source |
| Short citations | 0 | grounded quotes shorter than three words |
| Risk-flag accuracy (legacy) | 0.50 | blind to false positives; excluded from release decisions |
```


## Two separate gates

`make test` runs `demo-regression-policy.v2`, a threshold gate against the deliberately
imperfect bundled fixture. It detects regression. Passing it means nothing changed
unexpectedly; it does not mean an output is fit for use.

The [release certificate](../examples/release-certificate.md) is the eligibility decision,
under `strict-legal-release-policy.v2.1`. Eleven requirements live in one typed registry
that drives the decision, the policy the certificate publishes, the scores each case
reports, and what the verifier expects. A case reaches `PILOT_ELIGIBLE` only when all
eleven pass. An unsupported citation, grounding below 100 percent or a citation shorter
than three words is a hard `REJECT`; every other shortfall is `HUMAN_REVIEW_REQUIRED`.
Policy v2.1 added the last blocker and a review item for a flagged clause with no
grounded citation inside it, because grounding is a substring match and a one-word quote
satisfied every placement check; a certificate issued under v2 is still verified under
the v2 registry.

Certificate schema v3 publishes every one of those eleven decision inputs. Earlier
certificates advertised a `risk_flag_accuracy_target` that no longer decided anything and
omitted the risk metrics that did, so a reader could not reconstruct the decision from the
artifact. Diagnostics, including legacy risk-flag accuracy and span coverage, are printed
in a separate table and never affect eligibility.

A green CI run is not an approved benchmark result. Every verification result publishes a
`verification_scope`: v1 certificates verify for integrity only, v2 certificates reproduce
under their frozen builder and the v2 registry while their inputs still match and degrade
to integrity only once an input moves, and v3 certificates reproduce in full under the
policy they publish. Schema v3 was issued under policy v2 from v0.5.2 to v0.7.0-rc1, so a
v3 certificate that names policy v2 is reproduced under the frozen v2 registry and the
result says so in a `note`; any other policy id is rebuilt under the current policy and
fails on `policy_mismatch`. Every result names the policy it applied in `policy`. An
unknown schema fails closed naming the value it saw.


## What it checks

- Clause precision and recall.
- Clause coverage by source span, independent of the review's own vocabulary.
- Risk identification precision, recall and F1, so over-flagging is penalised.
- Severity accuracy on identified risks, with a severity confusion count.
- Duplicate and self-contradicting risk flags.
- Citation grounding as an exact span of the normalised source.
- Unsupported or fabricated citations.
- Citations too short to be a quotation, and flagged clauses with no citation inside them.
- Input drift and suite-level release eligibility.
- Adversarial and subtle contract changes.
- Critical false reassurance and required abstention.
- Instruction-injection and semantic-invariance behavior.
- Repeated-run consistency and input-bound robustness verification.

