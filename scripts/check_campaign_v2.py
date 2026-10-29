"""Fail when the candidate campaign no longer matches its sources or gold sets."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.campaign_v2 import (  # noqa: E402
    CampaignError,
    CampaignV2,
    coverage_report,
    verify_against_sources,
)
from contract_eval.capture import text_sha256  # noqa: E402
from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.gold_v2 import ExpectedAnswerV2  # noqa: E402

CAMPAIGN = ROOT / "robustness" / "campaign.v2.candidate.json"
DRAFTS = ROOT / "annotations" / "drafts"


def verify_gold_hashes(campaign: CampaignV2, gold_texts: dict[str, str]) -> None:
    """Fail when a recorded gold hash no longer matches the committed draft.

    The generator records text_sha256 of each draft's UTF-8 text. verify_against_sources
    only sees the parsed gold, which cannot reproduce that hash, so the comparison is
    made here, where the drafts are read.
    """
    unrecorded = sorted(set(gold_texts) - set(campaign.gold_sha256))
    if unrecorded:
        raise CampaignError(f"campaign records no gold hash for {unrecorded}")
    for case, recorded in sorted(campaign.gold_sha256.items()):
        if case not in gold_texts:
            raise CampaignError(f"campaign names case {case!r} with no gold supplied")
        actual = text_sha256(gold_texts[case])
        if actual != recorded:
            raise CampaignError(
                f"{case}: gold has changed since the campaign was written\n"
                f"  recorded {recorded}\n  actual   {actual}"
            )


def main() -> int:
    campaign = CampaignV2.model_validate(json.loads(CAMPAIGN.read_text(encoding="utf-8")))
    sources, gold_texts, golds = {}, {}, {}
    for case in ALL_CASES:
        sources[case] = (ROOT / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
        gold_texts[case] = (DRAFTS / f"{case}.candidate.v2.json").read_text(encoding="utf-8")
        golds[case] = ExpectedAnswerV2.model_validate(json.loads(gold_texts[case]))

    verify_against_sources(campaign, sources, golds)
    verify_gold_hashes(campaign, gold_texts)
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
