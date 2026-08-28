"""Fail when committed robustness artifacts differ from an offline rebuild."""

from __future__ import annotations

import json
from pathlib import Path

from contract_eval.adapters import get_adapter
from contract_eval.cases import ALL_CASES
from contract_eval.cli import evaluate_case
from contract_eval.release_certificate import build_release_certificate
from contract_eval.robustness import (
    build_robustness_report,
    render_robustness_html,
    render_robustness_markdown,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    scores = {
        case: evaluate_case(case, live=False)
        for case in ALL_CASES
    }
    report = build_robustness_report(
        ROOT / "robustness" / "campaign.v1.json",
        get_adapter(False),
        build_release_certificate(scores, root=ROOT),
        root=ROOT,
    )
    expected = {
        "adversarial-robustness-report.json": json.dumps(report, indent=2) + "\n",
        "adversarial-robustness-report.md": render_robustness_markdown(report),
        "adversarial-robustness-report.html": render_robustness_html(report),
    }
    drift: list[str] = []
    for name, document in expected.items():
        path = ROOT / "examples" / name
        if not path.is_file():
            drift.append(f"missing committed artifact: examples/{name}")
        elif path.read_text(encoding="utf-8") != document:
            drift.append(f"generated artifact drift: examples/{name}")
    if drift:
        print("\n".join(drift))
        print("Run `make robustness` and commit the regenerated artifacts.")
        return 1
    print("robustness artifact check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
