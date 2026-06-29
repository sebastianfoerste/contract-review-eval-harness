# Live frontier-model run: claude-opus-4-8, 2026-06-29

This is a dated snapshot of the optional live path. It measures a real frontier model
against the same synthetic contracts and hand-authored answer sets used by the offline
stub. Live output is non-deterministic, so these numbers document this run, not a
stable benchmark.

## Metadata

| Field | Value |
|---|---|
| Model id | `claude-opus-4-8` |
| Provider path | Anthropic Messages API through `src/contract_eval/adapters/live.py` |
| Model choice | Selected as the strongest current Anthropic model documented on 2026-06-29 |
| Captured run | Run 3 of 3 |
| Captured timestamp | 2026-06-29 08:34:32 CEST |
| Command | `make demo-live` |
| Evaluated cases | `all` (`nda`, `saas`) |
| Harness version | `0.1.0` |
| Base commit before evidence commit | `bf017c0` |
| Adapter config | `max_tokens=2000`, JSON-only review prompt, no raw provider response committed |
| Quality gate | Failed, because at least one clause F1 score was below `0.85` |
| Data posture | Synthetic contracts only, no client agreement, no API key, no raw provider response |

## Captured scorecard

# Contract Review Eval Scorecard: ALL CASES

## Case: nda

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.40 | predicted clause types that were expected |
| Clause recall | 0.40 | expected clause types that were found |
| Clause F1 | 0.40 | harmonic mean of precision and recall |
| Risk-flag accuracy | 0.50 | risky clauses flagged at the expected severity |
| Citation grounding | 1.00 | 5/5 quotes grounded in the source (exact match or 85%+ token overlap) |
| Hallucination count | 0 | cited quotes not grounded in the source |

## Case: saas

| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | 0.80 | predicted clause types that were expected |
| Clause recall | 0.80 | expected clause types that were found |
| Clause F1 | 0.80 | harmonic mean of precision and recall |
| Risk-flag accuracy | 1.00 | risky clauses flagged at the expected severity |
| Citation grounding | 1.00 | 5/5 quotes grounded in the source (exact match or 85%+ token overlap) |
| Hallucination count | 0 | cited quotes not grounded in the source |

## Three-run variance check

| Run | Timestamp | NDA F1 | NDA risk accuracy | NDA citation grounding | SaaS F1 | SaaS risk accuracy | SaaS citation grounding | Gate result |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 2026-06-29 08:33:32 CEST | 0.40 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | Failed on NDA F1 |
| 2 | 2026-06-29 08:34:05 CEST | 0.40 | 0.50 | 1.00 | 0.80 | 0.50 | 1.00 | Failed on NDA and SaaS F1 |
| 3 | 2026-06-29 08:34:32 CEST | 0.40 | 0.50 | 1.00 | 0.80 | 1.00 | 1.00 | Failed on NDA and SaaS F1 |

## Interpretation

The live model grounded all emitted citations in these three runs and produced zero
hallucination-count findings. The clause extraction scores were unstable and below the
current quality gate for the NDA case in every run. The SaaS case moved between a clean
pass and an F1 failure across repeated calls.

That is the point of the harness: quality is measured against a gold answer set and
review gate, not asserted from model reputation.
