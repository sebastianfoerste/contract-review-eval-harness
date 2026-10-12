# Product feedback notes

The scorecard is not just a customer artifact — each failing dimension is a product
requirement. Below, the seeded NDA failures rewritten as input for Product and Engineering.

## 1. Fabricated citations (Hallucination count = 1)
**Signal:** one cited quote (`notices shall be deemed received three business days after posting`)
does not appear in the source contract.

**Requirement:** every citation the model emits must be verified against the source before
it reaches the user; ungrounded quotes are dropped, not shown. Acceptance: citation-grounding
rate is enforced at output time, not just measured after the fact.

**Priority:** highest. A fabricated citation in a legal tool is a trust-ending event.

## 2. Wrong severity (Severity accuracy = 0.60)
**Signal:** the `assignment` clause, which permits assignment to a competitor without
consent, was flagged `low`; the answer set says `high`. The `permitted_disclosure` clause
was flagged `medium`; the answer set says `high`. Three of the five risks flagged on both
sides carry the expected severity.

**Requirement:** severity calibration on risk flags, ideally tunable per practice group,
since "risky" is partly a house view. Acceptance: severity accuracy above an agreed
threshold on the customer's own answer set.

**Priority:** high. Under-calling a risk is worse than over-calling it.

## 3. Over-extraction (Clause precision = 0.92)
**Signal:** the model reported an `indemnification` clause the NDA does not contain.

**Requirement:** suppress clause types with no grounded supporting text. Acceptance: clause
precision at or near 1.00 on the answer set.

**Priority:** medium. Noisy but not dangerous, and it erodes reviewer trust over time.

The fixture seeds two further failures that these notes do not yet turn into requirements:
one over-flag (`governing_law`, risk precision 0.83) and one missed risk (`notices`, risk
recall 0.83).

The pattern to take to Engineering: ground first, calibrate second, de-noise third.
