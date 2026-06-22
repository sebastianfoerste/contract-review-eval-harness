# Product feedback notes

The scorecard is not just a customer artifact — each failing dimension is a product
requirement. Below, the seeded NDA failures rewritten as input for Product and Engineering.

## 1. Fabricated citations (Hallucination count = 1)
**Signal:** one cited quote (`automatically renews for successive twelve (12) month periods`)
does not appear in the source contract.

**Requirement:** every citation the model emits must be verified against the source before
it reaches the user; ungrounded quotes are dropped, not shown. Acceptance: citation-grounding
rate is enforced at output time, not just measured after the fact.

**Priority:** highest. A fabricated citation in a legal tool is a trust-ending event.

## 2. Wrong severity (Risk-flag accuracy = 0.50)
**Signal:** the broad, unmarked-information `definition` clause was flagged `low`; the
answer set says `medium`.

**Requirement:** severity calibration on risk flags, ideally tunable per practice group,
since "risky" is partly a house view. Acceptance: risk-flag accuracy above an agreed
threshold on the customer's own answer set.

**Priority:** high. Under-calling a risk is worse than over-calling it.

## 3. Over-extraction (Clause precision = 0.83)
**Signal:** the model reported an `indemnification` clause the NDA does not contain.

**Requirement:** suppress clause types with no grounded supporting text. Acceptance: clause
precision at or near 1.00 on the answer set.

**Priority:** medium. Noisy but not dangerous, and it erodes reviewer trust over time.

The pattern to take to Engineering: ground first, calibrate second, de-noise third.
