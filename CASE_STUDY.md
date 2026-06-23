# Case study — contract-review-eval-harness

> Legal AI quality should be measured, not asserted. Synthetic data only; not legal advice.

## Problem
Teams adopt AI contract review on vibes: a demo looks impressive, so it ships. But "looks good" is not a quality bar. The failures that matter to a lawyer — a risk flagged at the wrong severity, a citation to a clause that isn't in the document — are exactly the ones a quick read misses. Without measurement, a firm cannot tell a good model from a confident one.

## Users
A legal engineer, innovation lead, or GC evaluating an AI contract-review tool before rollout — and anyone who needs to defend that decision afterwards.

## Workflow
1. A synthetic NDA and a hand-authored **gold answer set** (expected clauses, risks, citations) are provided.
2. The harness runs the AI output against the gold set.
3. It scores clause coverage (precision/recall), risk-flag accuracy, and citation grounding, and counts hallucinated citations.
4. It writes a **scorecard** (`examples/scorecard.md` + `.json`) with an overall verdict.

## Controls
Grounding is checked against the actual document text, not the model's confidence. Any single ungrounded citation forces a **REJECT** verdict regardless of other scores — the harness is deliberately conservative. The gold set is human-authored, so the benchmark itself is reviewable.

## Evaluation
The bundled run scores strong coverage but **catches a fabricated citation** ("Section 4.3 — Required Disclosures," which does not exist in the NDA) and a HIGH risk under-rated as LOW — and rejects the output. The point of the demo is to catch quietly plausible output a tired reviewer would pass.

## Limitations
It evaluates against a structured gold set for a synthetic NDA; it is not a general contract-understanding benchmark, and it does not read arbitrary contracts end to end. The gold set encodes one reviewer's judgment.

## Next steps
Expand the gold sets to more agreement types (DPA, MSA, SaaS order form); add inter-annotator review of the gold set; wire the harness into CI so a model/prompt change must clear the bar before merge.
