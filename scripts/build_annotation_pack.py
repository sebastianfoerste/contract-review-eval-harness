"""Build the blind annotation pack for the second annotator.

Blindness is the whole value of the exercise. If Annotator B can see the existing
gold, the aliases, the model output or the current severities, agreement statistics
measure influence rather than independent judgment.

The pack therefore carries only the contracts, the review context, the guideline and
empty templates. Everything withheld is listed explicitly in the manifest so the
exclusion can be audited rather than trusted.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.capture import canonical_sha256, text_sha256  # noqa: E402
from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.gold_v2 import ExpectedAnswerV2  # noqa: E402

OUT = ROOT / "annotations" / "pack"

EXCLUDED = [
    "expected/*.json (the current authoritative gold set)",
    "annotations/drafts/*.candidate.v2.json (Annotator A's candidate obligations)",
    "clause_aliases (Annotator A's vocabulary choices)",
    "severity rationales (Annotator A's calibration)",
    "examples/raw-output/* and examples/captures/* (model output)",
    "examples/scorecard*, examples/release-certificate*, examples/live-run-* (scores)",
    "examples/adversarial-robustness-report.* (campaign results)",
    "docs/ANNOTATION_GUIDELINE.md (maintainer guideline; discusses scoring and aliases)",
]


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "contracts").mkdir(parents=True)
    (OUT / "templates").mkdir(parents=True)

    files: dict[str, str] = {}

    for case in ALL_CASES:
        source_text = (ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
        target = OUT / "contracts" / f"{case}_sample.md"
        target.write_text(source_text, encoding="utf-8")
        files[f"contracts/{case}_sample.md"] = text_sha256(source_text)

        # Review context travels: a severity cannot be assigned without knowing whose
        # review it is. The candidate obligations do not.
        candidate = ExpectedAnswerV2.model_validate(
            json.loads((ROOT / "annotations" / "drafts" / f"{case}.candidate.v2.json")
                       .read_text(encoding="utf-8"))
        )
        context = candidate.review_context.model_dump(mode="json")
        context["annotator_id"] = "annotator-b"
        context["annotation_status"] = "draft"

        template = {
            "schema": "contract-review-eval.expected-answer.v2",
            "case": case,
            "review_context": context,
            "comment": (
                "Blind annotation by Annotator B. Record every atomic obligation you "
                "would review in this agreement, with raw character offsets into the "
                "contract as provided. Assign a severity only where you would flag a "
                "risk, and state why in writing."
            ),
            "thresholds": {},
            "obligations": [],
        }
        path = OUT / "templates" / f"{case}.annotator-b.v2.json"
        blob = json.dumps(template, indent=2, ensure_ascii=False) + "\n"
        path.write_text(blob, encoding="utf-8")
        files[f"templates/{case}.annotator-b.v2.json"] = text_sha256(blob)

    # The repository's own guideline is written for whoever maintains the harness. It
    # discusses scoring, fixtures and alias methodology, none of which a blind
    # annotator should see: it would leak both the metric surface and Annotator A's
    # approach. The pack ships a purpose-written annotator guideline instead.
    guideline = _annotator_guideline()
    (OUT / "ANNOTATOR_GUIDELINE.md").write_text(guideline, encoding="utf-8")
    files["ANNOTATOR_GUIDELINE.md"] = text_sha256(guideline)

    ledger = _primary_law_ledger()
    (OUT / "primary-law-ledger.md").write_text(ledger, encoding="utf-8")
    files["primary-law-ledger.md"] = text_sha256(ledger)

    manifest = {
        "schema": "contract-review-eval.annotation-pack.v1",
        "pack_id": "blind-annotation-2026-09-02",
        "annotator": "annotator-b",
        "cases": list(ALL_CASES),
        "files": dict(sorted(files.items())),
        "excluded_from_pack": EXCLUDED,
        "instructions": (
            "Work only from the contracts and the guideline in this pack. Do not consult "
            "the repository's expected/ directory, any model output, or any published "
            "score before returning your annotations."
        ),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    (OUT / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"pack built at {OUT.relative_to(ROOT)}")
    print(f"  {len(files)} files, manifest {manifest['manifest_sha256'][:16]}")
    print(f"  {len(EXCLUDED)} categories explicitly withheld")
    print("\nNOT SENT. Transmission requires explicit approval.")
    return 0


def _annotator_guideline() -> str:
    return """# Annotator guideline

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
"""


def _primary_law_ledger() -> str:
    return """# Primary-law reference ledger

Provided so a statutory conclusion can cite its provision. It is a pointer list, not a
view: it deliberately contains no assessment of the agreements in this pack.

## Regulation (EU) 2016/679 (GDPR)

- Art. 28(2) and 28(3)(d): sub-processor authorisation.
- Art. 28(3)(a): processing on documented instructions.
- Art. 28(3)(b): confidentiality of authorised persons.
- Art. 28(3)(c) and Art. 32: security of processing.
- Art. 28(3)(e) and Chapter III: assistance with data subject rights.
- Art. 28(3)(f), Art. 33 and Art. 35: breach notification and impact assessments.
- Art. 28(3)(g): deletion or return at the end of processing.
- Art. 28(3)(h): information, audits and inspections.
- Chapter V, Art. 44 to 49: transfers to third countries.

## Guidance

- EDPB Guidelines 07/2020 on the concepts of controller and processor.

Record for each risk whether it rests on law, regulatory guidance, market practice, or
your own legal judgment. Market-practice propositions must stay separately identified
from statutory conclusions.
"""


if __name__ == "__main__":
    raise SystemExit(main())
