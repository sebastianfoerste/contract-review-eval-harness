"""Campaign v2: mutations addressed by raw offsets, keyed to obligation ids.

v1 mutations matched an anchor string and required it to occur exactly once. That
worked, but it could not say which obligation a scenario was aimed at, and it could
not tell whether an edit had quietly destroyed the span some other obligation lives
in. Offsets fix both.

A mutation carries the slice it expects to replace and the hash of the source it was
written against. If either has moved, the campaign fails before any adapter is
invoked, because a scenario applied to text it was not written for is measuring
something nobody designed.

    obligations + source
            |
            v
    [mutation: raw span + expected slice + replacement]
            |
            v
    apply in descending offset order  ->  mutated source
            |
            v
    span transform  ->  obligation spans valid in the mutated document
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract_eval.capture import text_sha256
from contract_eval.gold_v2 import ExpectedAnswerV2, Obligation

CAMPAIGN_SCHEMA_V2 = "contract-review-eval.robustness-campaign.v2"

ScenarioKind = Literal[
    "obligation_removed",
    "obligation_inverted",
    "threshold_changed",
    "missing_schedule",
    "conflicting_clause",
    "instruction_injection",
    "semantic_control",
]

# Kinds that must change the review's answer. A control and an injection must not.
ANSWER_CHANGING: frozenset[str] = frozenset({
    "obligation_removed",
    "obligation_inverted",
    "threshold_changed",
    "missing_schedule",
    "conflicting_clause",
})


class MutationV2(BaseModel):
    """One edit, addressed by raw offsets into the base source."""

    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    expected_slice: str
    replacement: str

    @model_validator(mode="after")
    def validate_span(self) -> "MutationV2":
        if self.start > self.end:
            raise ValueError(f"mutation start {self.start} exceeds end {self.end}")
        return self


class ScenarioV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    case: str
    kind: ScenarioKind
    description: str
    target_obligation_ids: list[str] = Field(default_factory=list)
    # Obligations other than the target whose spans this edit knowingly disturbs.
    declared_affected_ids: list[str] = Field(default_factory=list)
    mutations: list[MutationV2] = Field(min_length=1)
    expects_answer_change: bool
    expects_abstention_for: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scenario(self) -> "ScenarioV2":
        if self.kind in ANSWER_CHANGING and not self.expects_answer_change:
            raise ValueError(
                f"{self.scenario_id}: kind {self.kind!r} must expect an answer change"
            )
        if self.kind in ("semantic_control", "instruction_injection") and self.expects_answer_change:
            raise ValueError(
                f"{self.scenario_id}: kind {self.kind!r} must not expect an answer change"
            )
        if self.kind in ANSWER_CHANGING and not self.target_obligation_ids:
            raise ValueError(f"{self.scenario_id}: an answer-changing scenario needs a target")
        return self


class CampaignV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.robustness-campaign.v2"] = Field(
        default=CAMPAIGN_SCHEMA_V2, alias="schema"
    )
    campaign_id: str
    generated_at_utc: str
    status: Literal["candidate", "frozen"] = "candidate"
    source_sha256: dict[str, str]
    gold_sha256: dict[str, str]
    scenarios: list[ScenarioV2] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> "CampaignV2":
        ids = [s.scenario_id for s in self.scenarios]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate scenario ids: {duplicates}")
        return self


class CampaignError(RuntimeError):
    """A scenario cannot be applied to the source it names."""


def apply_mutations(source: str, scenario: ScenarioV2) -> str:
    """Apply a scenario's edits to the source.

    Descending offset order, so an earlier edit never shifts the offsets of one that
    has not been applied yet. Each edit verifies the slice it expects to replace, so a
    scenario written against a different revision fails loudly instead of silently
    cutting the wrong words out.
    """
    mutated = source
    for mutation in sorted(scenario.mutations, key=lambda m: -m.start):
        if mutation.end > len(mutated):
            raise CampaignError(
                f"{scenario.scenario_id}: span [{mutation.start}:{mutation.end}) is "
                f"outside a source of length {len(mutated)}"
            )
        actual = mutated[mutation.start : mutation.end]
        if actual != mutation.expected_slice:
            raise CampaignError(
                f"{scenario.scenario_id}: source has changed under this scenario\n"
                f"  expected: {mutation.expected_slice!r}\n"
                f"  actual:   {actual!r}"
            )
        mutated = mutated[: mutation.start] + mutation.replacement + mutated[mutation.end :]
    return mutated


def transform_spans(
    obligations: list[Obligation],
    scenario: ScenarioV2,
) -> dict[str, tuple[int, int] | None]:
    """Where each obligation lives after the scenario's edits.

    An obligation entirely before every edit keeps its span. One entirely after shifts
    by the net length change. One the edit reaches into is returned as None: its text
    no longer says what the gold set recorded, so pretending to know its span would
    invite scoring a review against a passage that no longer exists.
    """
    edits = sorted(scenario.mutations, key=lambda m: m.start)
    result: dict[str, tuple[int, int] | None] = {}

    for obligation in obligations:
        start, end = obligation.start, obligation.end
        shift = 0
        disturbed = False
        for mutation in edits:
            delta = len(mutation.replacement) - (mutation.end - mutation.start)
            if mutation.end <= start:
                shift += delta
            elif mutation.start >= end:
                continue
            else:
                disturbed = True
                break
        result[obligation.obligation_id] = None if disturbed else (start + shift, end + shift)
    return result


def validate_scenario_boundaries(
    obligations: list[Obligation],
    scenario: ScenarioV2,
) -> None:
    """Reject an edit that reaches into an obligation it never declared.

    Crossing a boundary silently is how a scenario aimed at one duty ends up also
    rewriting its neighbour, and then the campaign measures a change nobody intended.
    """
    declared = set(scenario.target_obligation_ids) | set(scenario.declared_affected_ids)
    spans = transform_spans(obligations, scenario)
    undeclared = sorted(
        oid for oid, span in spans.items() if span is None and oid not in declared
    )
    if undeclared:
        raise CampaignError(
            f"{scenario.scenario_id}: edits disturb undeclared obligations {undeclared}; "
            "add them to declared_affected_ids or narrow the mutation"
        )


def verify_against_sources(
    campaign: CampaignV2,
    sources: dict[str, str],
    golds: dict[str, ExpectedAnswerV2],
) -> None:
    """Fail before any adapter runs if the campaign no longer matches its inputs."""
    for case, recorded in sorted(campaign.source_sha256.items()):
        if case not in sources:
            raise CampaignError(f"campaign names case {case!r} with no source supplied")
        actual = text_sha256(sources[case])
        if actual != recorded:
            raise CampaignError(
                f"{case}: source has changed since the campaign was written\n"
                f"  recorded {recorded}\n  actual   {actual}"
            )

    known_ids = {
        o.obligation_id for gold in golds.values() for o in gold.obligations
    }
    for scenario in campaign.scenarios:
        # Parenthesised deliberately: `-` binds tighter than `|`, so writing
        # `a | b - known` means `a | (b - known)` and leaves the first set unfiltered.
        referenced = set(scenario.target_obligation_ids) | set(scenario.declared_affected_ids)
        unknown = sorted(referenced - known_ids)
        if unknown:
            raise CampaignError(
                f"{scenario.scenario_id}: references unknown obligations {unknown}"
            )
        validate_scenario_boundaries(list(golds[scenario.case].obligations), scenario)


def coverage_report(
    campaign: CampaignV2,
    golds: dict[str, ExpectedAnswerV2],
) -> dict[str, object]:
    """Which obligations the campaign exercises, and which per-case controls exist."""
    targeted: set[str] = set()
    for scenario in campaign.scenarios:
        if scenario.kind in ANSWER_CHANGING:
            targeted.update(scenario.target_obligation_ids)

    all_ids = {o.obligation_id for gold in golds.values() for o in gold.obligations}
    kinds_by_case: dict[str, set[str]] = {}
    for scenario in campaign.scenarios:
        kinds_by_case.setdefault(scenario.case, set()).add(scenario.kind)

    missing_controls = sorted(
        case for case in golds if "semantic_control" not in kinds_by_case.get(case, set())
    )
    missing_injection = sorted(
        case for case in golds
        if "instruction_injection" not in kinds_by_case.get(case, set())
    )
    missing_abstention = sorted(
        case for case in golds
        if "missing_schedule" not in kinds_by_case.get(case, set())
    )

    return {
        "obligations_total": len(all_ids),
        "obligations_targeted": len(targeted & all_ids),
        "untargeted_obligations": sorted(all_ids - targeted),
        "cases_without_semantic_control": missing_controls,
        "cases_without_instruction_injection": missing_injection,
        "cases_without_abstention_scenario": missing_abstention,
        "scenarios": len(campaign.scenarios),
        "complete": (
            not (all_ids - targeted)
            and not missing_controls
            and not missing_injection
            and not missing_abstention
        ),
    }
