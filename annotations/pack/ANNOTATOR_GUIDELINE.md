# Annotator guideline

You are recording, independently, which obligations a reviewer should identify in each
agreement in this pack, and which of them carry risk.

Work only from the contracts and this guideline. Do not consult the repository, any
model output, or anyone else's annotation of these documents before you return yours.

## What an obligation is

One atomic duty. If a sentence imposes two duties that could be complied with
separately, record two obligations. Prefer the granularity at which you would actually
negotiate: a clause you would accept in part and reject in part is more than one duty.

Give each obligation:

- An id of the form `<case>.<short_name>`, for example `nda.term`.
- A short label and a one-line description.
- `start` and `end`: zero-based Python character offsets into the contract file exactly
  as provided, half-open, so `source[start:end]` is the quoted text.
- `quote`: that exact slice, copied verbatim.

Anchor the span at the operative words of the duty rather than at a heading.

## Assigning severity

Assign a severity only where you would flag the clause to the client. Leave `risk`
null otherwise; a document where everything is flagged is not a review.

- `high`: the clause defeats a mandatory requirement, removes a right the counterparty
  cannot practically recover, or creates unquantified exposure. A regulator, court or
  auditor would treat it as a defect rather than a negotiating position.
- `medium`: materially worse than the market position and worth negotiating, but a
  reviewer who accepted it with reasons would not be negligent.
- `low`: unusual or slightly off-market, worth a note.

Calibrate against the instrument, not against how unusual the drafting looks. A
familiar-looking clause that defeats a mandatory requirement is `high`.

## Say what your severity rests on

Every risk carries a written rationale and a `source_category`:

- `law`: a statutory or regulatory requirement. Cite the provision in
  `source_reference`.
- `regulatory_guidance`: supervisory guidance. Cite it.
- `market_practice`: what the market ordinarily accepts. No citation required, and it
  must not be presented as a legal conclusion.
- `legal_judgment`: your own assessment on an open point.

Keeping these apart matters more than the severity itself. A market-practice view
dressed as a statutory conclusion is the failure this exercise exists to catch.

## Where you are unsure

Record the obligation and state the uncertainty in the rationale. Disagreement is
expected and will be adjudicated; a hedge you wrote down is useful, and one you left
out is not.
