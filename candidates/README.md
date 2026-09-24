# Candidate cases

Two synthetic contracts that are not yet part of the evaluated suite:

| Case | Contract | Why it is a candidate |
|---|---|---|
| `nda_de` | German-language NDA, reviewed for the disclosing party | Tests extraction and grounding on German contract text |
| `spa` | English-language SPA excerpt under German law, reviewed for the purchaser | Adds a transactional document type to the NDA, SaaS and DPA cases |

Neither case appears in `ALL_CASES` in `src/contract_eval/cases.py`, so no score,
certificate or robustness run includes them.

## What is missing

The answer sets in `candidates/expected/` are empty by design. The harness claims
hand-authored gold answers, so the clause types, risk flags, severity rationales, aliases
and verbatim anchors for these two contracts have to be written by the reviewing lawyer,
following the structure of `expected/nda.json`.

## Promotion checklist

1. Author `candidates/expected/<case>.json`, including `risk_appetite`.
2. Move the contract to `data/<case>_sample.md` and the answer set to `expected/<case>.json`.
3. Write `fixtures/<case>_stub.json` with deliberately imperfect output, as described in `data/README.md`.
4. Add the case to `ALL_CASES`.
5. Run `make test`, `make anchor-check` and `make certificate`, then review the changed certificate and web export before committing.
