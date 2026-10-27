# Matter: Northwind and the Cverbio LabTrace platform (SYNTHETIC)

A fictional customer, Northwind Materials GmbH, is buying a hosted analytics platform
from a fictional vendor on the vendor's paper. Every document is fabricated. No real
company, person or agreement is represented.

## Documents

| Id | Kind | Round | File |
|---|---|---|---|
| `nda` | contract | 1 | `data/nda_sample.md` |
| `saas` | contract | 1 | `data/saas_sample.md` |
| `dpa` | contract | 1 | `data/dpa_sample.md` |
| `negotiation_record` | negotiation record | 1 | `documents/negotiation_record.md` |
| `security_questionnaire` | security questionnaire | 1 | `documents/security_questionnaire.md` |
| `client_instructions` | client instruction | 1 | `documents/client_instructions.md` |
| `playbook` | playbook | 1 | `documents/playbook.md` |
| `vendor_response` | counterparty response | 2 | `documents/vendor_response.md` |
| `client_update` | client instruction | 2 | `documents/client_update.md` |

The three contracts are the certified cases of this repository, referenced in place
and unchanged. Their single-contract answers under `expected/` are not affected.

## Rounds

1. **First review of the vendor paper.** The three contracts, what the vendor has said
   so far, and what the client wants.
2. **Vendor response and changed facts.** The vendor answers the mark-up. The client
   then changes the data in scope, the timetable and its audit requirement.

## Status

| Part | Status |
|---|---|
| Six matter documents | Reviewed and calibrated |
| Prompts for the three conditions | Drafted. Untuned |
| Answers, round 1 and round 2 | Draft answers authored |
| Stub outputs | None. Written after the answers, deliberately imperfect, as for the cases |
| Live outputs | One: round 1 under `matter` (claude-sonnet-5-5, 2026-10-07), scored once against the draft answers and logged in `experiments/northwind-saas/log.jsonl`. The capture is not committed |
| Reviewer sessions | None recorded. `session-template-round1.json` is a blank session for that output |

No stub output exists, so `matter-evaluate` scores nothing offline. The logged run
covers one condition of round 1 and measures no difference between conditions.

The documents contain deliberate tensions between the contracts, the vendor's
statements and the client's position. They are not listed anywhere in this repository,
so that the answers are written from the documents and not from a list.

See [`docs/MATTER_EVALUATION.md`](../../docs/MATTER_EVALUATION.md) for the method and
for how to write the answers.
