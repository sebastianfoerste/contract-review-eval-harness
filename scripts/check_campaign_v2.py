"""Fail when the candidate campaign no longer matches its sources or gold sets."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.campaign_v2 import (  # noqa: E402
    CampaignV2,
    coverage_report,
    verify_against_sources,
)
from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.gold_v2 import ExpectedAnswerV2  # noqa: E402

CAMPAIGN = ROOT / "robustness" / "campaign.v2.candidate.json"


def main() -> int:
    campaign = CampaignV2.model_validate(json.loads(CAMPAIGN.read_text(encoding="utf-8")))
    sources, golds = {}, {}
    for case in ALL_CASES:
        sources[case] = (ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
        golds[case] = ExpectedAnswerV2.model_validate(
            json.loads(
                (ROOT / "annotations" / "drafts" / f"{case}.candidate.v2.json")
                .read_text(encoding="utf-8")
            )
        )

    verify_against_sources(campaign, sources, golds)
    report = coverage_report(campaign, golds)

    if not report["complete"]:
        print("campaign coverage is incomplete:")
        for key in (
            "untargeted_obligations",
            "cases_without_semantic_control",
            "cases_without_instruction_injection",
            "cases_without_abstention_scenario",
        ):
            if report[key]:
                print(f"  {key}: {report[key]}")
        print("run `make campaign-v2` to regenerate")
        return 1

    print(
        f"campaign v2 check passed: {report['scenarios']} scenarios, "
        f"{report['obligations_targeted']}/{report['obligations_total']} obligations "
        f"targeted, status {campaign.status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
