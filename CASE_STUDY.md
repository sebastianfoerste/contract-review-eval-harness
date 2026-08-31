# Case study — contract-review-eval-harness

> Legal AI quality should be measured, not asserted. Synthetic data only; not legal advice.

## Problem
Teams adopt AI contract review on vibes: a demo looks impressive, so it ships. But "looks good" is not a quality bar. The failures that matter to a lawyer — a risk flagged at the wrong severity, a citation to a clause that isn't in the document — are exactly the ones a quick read misses. Without measurement, a firm cannot tell a good model from a confident one.

## Users
A legal engineer, innovation lead, or GC evaluating an AI contract-review tool before rollout — and anyone who needs to defend that decision afterwards.

## Workflow
1. Three synthetic agreements — an NDA, a SaaS agreement and an Art. 28 GDPR data processing agreement — each with a hand-authored **gold answer set** (expected clauses, risks, citations).
2. The harness runs the AI output against the gold set.
3. It scores clause coverage (precision/recall), risk-flag accuracy, and citation grounding, and counts hallucinated citations.
4. It writes a **scorecard** (`examples/scorecard.md` + `.json`) with an overall verdict.
5. An **adversarial campaign** replays eighteen minimal-pair mutations across the three agreements and asks whether the review moved when the contract did.

## Controls
Grounding is checked against the actual document text, not the model's confidence. Any single ungrounded citation forces a **REJECT** verdict regardless of other scores — the harness is deliberately conservative. The gold set is human-authored, so the benchmark itself is reviewable.

## Evaluation
The bundled run scores strong coverage but **catches a fabricated citation** ("Section 4.3 — Required Disclosures," which does not exist in the NDA) and a HIGH risk under-rated as LOW — and rejects the output. The point of the demo is to catch quietly plausible output a tired reviewer would pass.

Every case makes that gap explicit. The offline adapter reaches **0.95 to 0.96 clause F1** across all three — it finds every expected clause — against 0.50 to 0.60 risk-flag accuracy. On the DPA it rates an excluded on-site inspection right and a transfer clause carrying no Chapter V mechanism as low risk. On the SaaS agreement it rates a perpetual licence to train models on Customer Personal Data, and an indemnity requiring the customer to cover the provider's own IP infringement, as low risk. A reviewer reading only the coverage number would approve all three.

The adversarial campaign returns **REJECT** against the bundled adapter, and the release certificate rejects all three cases. An instrument that cannot fail proves nothing; this one fails on its own baseline.

## Limitations
It evaluates against structured gold sets for three synthetic agreements totalling thirty-two clause types; it is not a general contract-understanding benchmark, and it does not read arbitrary contracts end to end. The gold sets encode one reviewer's judgment and have had no second-annotator review, though each severity now carries a written rationale that can be challenged.

## Next steps
Add inter-annotator review of the severity rationales; extend the campaign to cover the newly added clause types; publish dated scorecards across model versions using `--model`, naming the model, the date and the harness version each time.

Three earlier next steps have shipped: the DPA is the third evaluated agreement type, the gold sets carry written severity rationales under a documented annotation guideline, and CI runs the certificate and robustness gates so a change must clear the bar before merge.
