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
from contract_eval.scorer import build_normalized_index, normalize_text  # noqa: E402

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


def locate(index, anchor: str, clause: str) -> tuple[int, int]:
    """Resolve a v1 anchor to raw offsets.

    The anchor was written to match normalised text, so a raw `find` fails wherever
    the clause wraps across a line. Matching normalised and mapping back is the only
    way to recover the offsets the obligation actually occupies.
    """
    spans = index.find_all(normalize_text(anchor))
    if not spans:
        raise SystemExit(f"{clause}: anchor not found: {anchor!r}")
    if len(spans) > 1:
        raise SystemExit(f"{clause}: anchor is ambiguous, {len(spans)} matches: {anchor!r}")
    return spans[0]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0

    for case in ALL_CASES:
        source = (ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
        index = build_normalized_index(source)
        v1 = ExpectedAnswer.model_validate(
            json.loads((ROOT / "expected" / f"{case}.json").read_text(encoding="utf-8"))
        )
        aliases_by_target: dict[str, list[str]] = {}
        for alias, target in v1.clause_aliases.items():
            aliases_by_target.setdefault(target, []).append(alias)

        obligations = []
        for clause in v1.clause_types:
            anchor = v1.clause_anchors[clause]
            start, end = locate(index, anchor, clause)
            base_id = f"{case}.{clause}"
            severity = v1.risk_flags.get(clause)
            rationale = v1.severity_rationale.get(clause)

            targets = SPLITS.get(base_id, [(base_id, clause.replace("_", " ").title(), "")])
            for obligation_id, label, description in targets:
                risk = None
                if severity:
                    note = rationale or ""
                    if len(targets) > 1:
                        note = (
                            f"CARRIED OVER FROM THE COMPOSITE v1 CLAUSE {base_id}. "
                            f"Severity for this atomic duty is NOT yet calibrated "
                            f"separately and must be adjudicated. Original note: {note}"
                        )
                    risk = {
                        "severity": severity,
                        "rationale": note,
                        "source_category": SOURCE_CATEGORY[case],
                        "source_reference": SOURCE_REFERENCE.get(case),
                    }
                obligations.append({
                    "obligation_id": obligation_id,
                    "label": label,
                    "description": description or f"Derived from v1 clause {clause}.",
                    "start": start,
                    "end": end,
                    "quote": source[start:end],
                    "aliases": sorted(aliases_by_target.get(clause, [])),
                    "risk": risk,
                    "adjudication_note": (
                        "Shares a span with the sibling duty split from the same v1 clause; "
                        "boundaries require adjudication."
                        if len(targets) > 1 else None
                    ),
                })

        context = v1.review_context
        payload = {
            "schema": "contract-review-eval.expected-answer.v2",
            "case": case,
            "review_context": {
                "party": context.party,
                "commercial_perspective": "Receiving side; conservative pre-signature review.",
                "governing_law": context.governing_law,
                "jurisdiction": "Germany",
                "objective": context.objective,
                "risk_appetite": context.risk_appetite,
                "playbook_id": None,
                "legal_position_date": "2026-09-02",
                "annotator_id": "annotator-a",
                "annotation_status": "candidate",
                "adjudication_status": "not_started",
            },
            "comment": (
                "CANDIDATE, NOT AUTHORITATIVE. Offsets derived mechanically from v1 anchors; "
                "severities carried over from a single annotator. Requires blind second "
                "annotation and adjudication before replacing expected/*.json."
            ),
            "thresholds": dict(v1.thresholds),
            "obligations": obligations,
        }
        path = OUT / f"{case}.candidate.v2.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        total += len(obligations)
        print(f"{case}: {len(obligations)} candidate obligations -> {path.relative_to(ROOT)}")

    print(f"total candidate obligations: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
