"""Derive v2 stub fixtures from the v1 ones.

Mechanical, so the deliberate imperfections carry over unchanged: the same spurious
clause, the same under-rated severities, the same single fabricated citation. Only the
shape changes. Hand-writing the v2 stubs would risk quietly making them easier.

Evidence links are inferred from the v1 `clause_type` field, which is the only thing
connecting a v1 finding to a v1 citation. A finding whose clause type matches no
citation gets no evidence, which is correct: in v1 that assertion had nothing behind
it, and v2 simply makes the absence visible.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.review_v2 import ReviewOutputV2  # noqa: E402


def convert(v1: dict) -> dict:
    citations = []
    by_clause: dict[str, list[str]] = {}
    for index, citation in enumerate(v1.get("citations", []), start=1):
        citation_id = f"c{index}"
        citations.append({"citation_id": citation_id, "quote": citation["quote"]})
        by_clause.setdefault(citation["clause_type"], []).append(citation_id)

    clauses = [
        {
            "finding_id": f"f{index}",
            "clause_type": clause["clause_type"],
            "text": clause["text"],
            "evidence": by_clause.get(clause["clause_type"], []),
        }
        for index, clause in enumerate(v1.get("clauses", []), start=1)
    ]
    risk_flags = [
        {
            "risk_id": f"r{index}",
            "clause_type": flag["clause_type"],
            "severity": flag["severity"],
            "rationale": flag["rationale"],
            "evidence": by_clause.get(flag["clause_type"], []),
        }
        for index, flag in enumerate(v1.get("risk_flags", []), start=1)
    ]
    abstentions = [
        {
            "abstention_id": f"a{index}",
            "clause_type": item["clause_type"],
            "reason": item["reason"],
            "evidence": by_clause.get(item["clause_type"], []),
        }
        for index, item in enumerate(v1.get("abstentions", []), start=1)
    ]

    return {
        "schema": "contract-review-eval.review-output.v2",
        "clauses": clauses,
        "risk_flags": risk_flags,
        "citations": citations,
        "abstentions": abstentions,
    }


def main() -> int:
    for case in ALL_CASES:
        v1 = json.loads((ROOT / "fixtures" / f"{case}_stub.json").read_text(encoding="utf-8"))
        payload = convert(v1)
        ReviewOutputV2.model_validate(payload)

        target = ROOT / "fixtures" / f"{case}_stub.v2.json"
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        unbacked = [f["finding_id"] for f in payload["clauses"] if not f["evidence"]]
        print(
            f"{case}: {len(payload['clauses'])} clauses, {len(payload['citations'])} citations, "
            f"{len(unbacked)} without evidence {unbacked}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
