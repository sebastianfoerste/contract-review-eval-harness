"""Derive candidate v2 obligations from the v1 gold sets.

Output goes to annotations/drafts/. It is a candidate set, not authoritative gold: the
offsets are derived mechanically from v1 anchors, and the severity calibration carries
over from a single annotator. Both need blind second annotation and adjudication before
anything here replaces expected/*.json.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.models import ExpectedAnswer  # noqa: E402
from contract_eval.upgrade import upgrade_gold  # noqa: E402

OUT = ROOT / "annotations" / "drafts"

# One v1 clause carries two distinct Art. 28(3) duties: lit. f notification and the
# DPIA assistance duty. Scoring them as one obligation is why a review that split them
# was scored as having missed a clause. Their separate severity calibration is left
# for adjudication rather than assumed here.
SPLITS = {
    "dpa.breach_and_dpia_assistance": [
        ("dpa.breach_notification", "Personal data breach notification",
         "Art. 28(3)(f) GDPR: assist the controller with notification of a personal data breach."),
        ("dpa.dpia_assistance", "Data protection impact assessment assistance",
         "Art. 28(3)(f) GDPR: assist the controller with data protection impact assessments."),
    ],
}

SOURCE_CATEGORY = {
    "dpa": "law",
    "nda": "legal_judgment",
    "saas": "market_practice",
}

SOURCE_REFERENCE = {
    "dpa": "Regulation (EU) 2016/679, Art. 28(3)",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0

    for case in ALL_CASES:
        source = (ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
        v1 = ExpectedAnswer.model_validate(
            json.loads((ROOT / "expected" / f"{case}.json").read_text(encoding="utf-8"))
        )
        # The straight upgrade lives in the library and is shared with every other
        # v1 entry point. This script adds only what is specific to migration: the
        # composite DPA clause covering two distinct Art. 28(3)(f) duties.
        upgraded = upgrade_gold(case, v1, source)
        payload = upgraded.model_dump(mode="json", by_alias=True)

        obligations = []
        for obligation in payload["obligations"]:
            targets = SPLITS.get(obligation["obligation_id"])
            if not targets:
                obligations.append(obligation)
                continue
            for obligation_id, label, description in targets:
                clone = dict(obligation)
                clone["obligation_id"] = obligation_id
                clone["label"] = label
                clone["description"] = description
                if clone.get("risk"):
                    risk = dict(clone["risk"])
                    risk["rationale"] = (
                        f"CARRIED OVER FROM THE COMPOSITE v1 CLAUSE "
                        f"{obligation['obligation_id']}. Severity for this atomic duty "
                        f"is NOT yet calibrated separately and must be adjudicated. "
                        f"Original note: {risk['rationale']}"
                    )
                    clone["risk"] = risk
                clone["adjudication_note"] = (
                    "Shares a span with the sibling duty split from the same v1 clause; "
                    "boundaries require adjudication."
                )
                obligations.append(clone)

        payload["obligations"] = obligations
        payload["comment"] = (
            "CANDIDATE, NOT AUTHORITATIVE. Offsets derived from v1 anchors; severities "
            "carried over from a single annotator. Requires blind second annotation and "
            "adjudication before replacing expected/*.json."
        )

        path = OUT / f"{case}.candidate.v2.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        total += len(obligations)
        print(f"{case}: {len(obligations)} candidate obligations -> {path.relative_to(ROOT)}")

    print(f"total candidate obligations: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
