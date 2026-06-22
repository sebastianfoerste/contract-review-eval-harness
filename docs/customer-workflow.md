# Customer workflow

How an evaluation harness fits a real adoption motion.

## The trust objection
Early in a rollout, a partner or general counsel asks the question that stalls deals:
"How do I know it is not making things up?" An eval harness is the answer you can show
rather than argue.

## Build the answer set with the customer
Sit with the practice group and capture, for a representative contract type, which clause
types must be found and which clauses are risky and at what severity. That becomes
`expected/<case>.json`. The act of building it is itself an adoption exercise — it surfaces
how the group actually reviews.

## Run and read the scorecard together
Run the harness on a representative contract. Walk the scorecard live:
- Citation grounding is the trust number. Show it.
- The hallucination count is the safety number. If it is non-zero, show which quote failed and that it would be rejected.
- Risk-flag accuracy shows whether the model agrees with the group on what is risky.

## Set the review gate
The scorecard ends with "human review required." Use it to agree the operating rule: AI
produces the first pass, a named lawyer confirms every flag and citation before reliance.
That rule is what makes the tool adoptable inside a regulated practice.

## Feed the result back
Whichever failure mode dominates — over-extraction, wrong severity, fabricated citation —
becomes a line of product feedback (see `product-feedback-notes.md`). The harness is both
a trust artifact for the customer and a requirements source for Product.
