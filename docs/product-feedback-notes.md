# Product feedback notes

The scorecard is not just a customer artifact — each failing dimension is a product
requirement. Below, the seeded NDA failures rewritten as input for Product and Engineering.

Figures are from the current `make demo` scorecard (NDA case, offline stub adapter, harness
0.7.0rc1). Earlier copies of this note quoted clause precision 0.83: that was harness 0.1.0
(2026-06-27), when the NDA answer set had five clause types and the stub reported six.

## 1. Fabricated citations (Hallucination count = 1)
**Signal:** one cited quote (`notices shall be deemed received three business days after
posting`) does not appear in the source contract, so citation grounding is 0.89 (8/9).

**Requirement:** every citation the model emits must be verified against the source before
it reaches the user; ungrounded quotes are dropped, not shown. Acceptance: citation-grounding
rate is enforced at output time, not just measured after the fact.

**Priority:** highest. A fabricated citation in a legal tool is a trust-ending event.

## 2. Wrong severity (Severity accuracy = 0.60; legacy risk-flag accuracy = 0.50)
**Signal:** the consent condition on legally compelled disclosure (`permitted_disclosure`)
was flagged `medium` and the free assignment to a competitor (`assignment`) `low`; the
answer set rates both `high`. The review also flags `governing_law`, which the answer set
does not treat as a risk, and misses the `notices` risk.

**Requirement:** severity calibration on risk flags, ideally tunable per practice group,
since "risky" is partly a house view. Acceptance: severity accuracy above an agreed
threshold on the customer's own answer set.

**Priority:** high. Under-calling a risk is worse than over-calling it.

## 3. Over-extraction (Clause precision = 0.92)
**Signal:** the model reported an `indemnification` clause the NDA does not contain, so 11
of its 12 clause types are expected ones.

**Requirement:** suppress clause types with no grounded supporting text. Acceptance: clause
precision at or near 1.00 on the answer set.

**Priority:** medium. Noisy but not dangerous, and it erodes reviewer trust over time.

The pattern to take to Engineering: ground first, calibrate second, de-noise third.
