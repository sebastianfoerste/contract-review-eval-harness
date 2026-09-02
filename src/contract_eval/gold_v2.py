"""Gold schema v2: atomic obligations anchored to raw source offsets.

v1 identified a clause by a name and a phrase anchor. Both are indirections a review
can miss for reasons that are not legal: it can call the clause something else, or
split one gold clause into two. v2 identifies an obligation by where it lives in the
document, which no vocabulary choice can change.

Offsets are zero-based Python character indices with half-open ends, `[start, end)`,
into the raw source text. Character indices, not UTF-8 byte offsets: a contract with
an umlaut or a typographic dash would otherwise silently shift every later span.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GOLD_SCHEMA_V2 = "contract-review-eval.expected-answer.v2"

Severity = Literal["low", "medium", "high"]
SourceCategory = Literal["law", "regulatory_guidance", "market_practice", "legal_judgment"]


class ReviewContextV2(BaseModel):
    """Whose review this gold set encodes. A severity is only defensible from a position."""

    model_config = ConfigDict(extra="forbid")

    party: str
    commercial_perspective: str
    governing_law: str
    jurisdiction: str
    objective: str
    risk_appetite: Literal["conservative", "balanced", "commercial"]
    playbook_id: str | None = None
    legal_position_date: str
    annotator_id: str
    annotation_status: Literal["draft", "candidate", "adjudicated", "frozen"]
    adjudication_status: Literal["not_started", "in_progress", "complete"]


class ObligationRisk(BaseModel):
    """Severity and its written justification are inseparable.

    A severity nobody wrote a reason for is an assertion. Keeping them in one object
    makes it impossible to record one without the other.
    """

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    rationale: str = Field(min_length=1)
    source_category: SourceCategory
    source_reference: str | None = None

    @model_validator(mode="after")
    def validate_risk(self) -> "ObligationRisk":
        if not self.rationale.strip():
            raise ValueError("rationale must contain non-whitespace text")
        # A statutory conclusion must cite the provision it rests on. A market-practice
        # proposition need not, and must not be dressed up as one.
        if self.source_category in ("law", "regulatory_guidance") and not self.source_reference:
            raise ValueError(
                f"source_category {self.source_category!r} requires a source_reference"
            )
        return self


class Obligation(BaseModel):
    """One atomic duty, located in the source by raw offsets."""

    model_config = ConfigDict(extra="forbid")

    obligation_id: str
    label: str
    description: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    risk: ObligationRisk | None = None
    adjudication_note: str | None = None

    @model_validator(mode="after")
    def validate_span(self) -> "Obligation":
        if self.start >= self.end:
            raise ValueError(
                f"{self.obligation_id}: start {self.start} must be less than end {self.end}"
            )
        return self


class ExpectedAnswerV2(BaseModel):
    """The authoritative answer set for one case."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.expected-answer.v2"] = Field(
        default=GOLD_SCHEMA_V2, alias="schema"
    )
    case: str
    review_context: ReviewContextV2
    comment: str = ""
    thresholds: dict[str, float] = Field(default_factory=dict)
    obligations: list[Obligation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_gold(self) -> "ExpectedAnswerV2":
        ids = [o.obligation_id for o in self.obligations]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate obligation ids: {duplicates}")

        prefix = f"{self.case}."
        misprefixed = sorted(i for i in ids if not i.startswith(prefix))
        if misprefixed:
            raise ValueError(
                f"obligation ids must start with {prefix!r}: {misprefixed}"
            )

        # Identical spans on distinct obligations are allowed only with a written
        # note. One sentence can carry two duties, but silently duplicating a span
        # makes evidence assignment ambiguous with no record of why.
        by_span: dict[tuple[int, int], list[str]] = {}
        for o in self.obligations:
            by_span.setdefault((o.start, o.end), []).append(o.obligation_id)
        for span, members in sorted(by_span.items()):
            if len(members) > 1:
                undocumented = [
                    o.obligation_id for o in self.obligations
                    if o.obligation_id in members and not o.adjudication_note
                ]
                if undocumented:
                    raise ValueError(
                        f"obligations {sorted(members)} share span {span} without an "
                        f"adjudication_note: {sorted(undocumented)}"
                    )
        return self

    def validate_against_source(self, source_text: str) -> None:
        """Every offset must resolve, and the recorded quote must be the bytes there.

        This is the invariant the whole schema rests on. If a quote and its offsets
        disagree, coverage is measured against text the gold set never saw.
        """
        length = len(source_text)
        for o in self.obligations:
            if o.end > length:
                raise ValueError(
                    f"{o.obligation_id}: end {o.end} exceeds source length {length}"
                )
            actual = source_text[o.start : o.end]
            if actual != o.quote:
                raise ValueError(
                    f"{o.obligation_id}: source[{o.start}:{o.end}] does not match the "
                    f"recorded quote\n  recorded: {o.quote!r}\n  actual:   {actual!r}"
                )

    def risk_obligations(self) -> dict[str, ObligationRisk]:
        return {o.obligation_id: o.risk for o in self.obligations if o.risk is not None}
