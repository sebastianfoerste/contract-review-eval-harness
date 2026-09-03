"""Review output v2: every finding names the evidence that supports it.

In v1 a clause finding and a citation were separate lists with no link between them.
A review could assert a clause and quote something unrelated, and nothing could tell
the difference. Scoring then had to guess which quote supported which finding, which
is the citation-misattribution gap this schema closes.

A finding carries citation ids. The citations resolve to source spans. The spans
resolve to obligations. A finding whose evidence does not resolve is unbound, and an
unbound finding earns nothing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REVIEW_SCHEMA_V2 = "contract-review-eval.review-output.v2"

Severity = Literal["low", "medium", "high"]


class CitationV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(description="Unique id for this citation, for example c1.")
    quote: str = Field(
        description=(
            "Text copied verbatim from the contract, character for character. "
            "Do not paraphrase, reorder or abbreviate."
        )
    )


class ClauseFindingV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    clause_type: str = Field(
        description="Descriptive name for the clause. Naming does not affect scoring."
    )
    text: str
    evidence: list[str] = Field(
        default_factory=list,
        description="Citation ids that support this finding.",
    )


class RiskFlagV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str
    clause_type: str
    severity: Severity
    rationale: str
    evidence: list[str] = Field(default_factory=list)


class AbstentionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstention_id: str
    clause_type: str
    reason: str
    evidence: list[str] = Field(default_factory=list)


class ReviewOutputV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.review-output.v2"] = Field(
        default=REVIEW_SCHEMA_V2, alias="schema"
    )
    clauses: list[ClauseFindingV2] = Field(default_factory=list)
    risk_flags: list[RiskFlagV2] = Field(default_factory=list)
    citations: list[CitationV2] = Field(default_factory=list)
    abstentions: list[AbstentionV2] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "ReviewOutputV2":
        citation_ids = [c.citation_id for c in self.citations]
        duplicates = sorted({i for i in citation_ids if citation_ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate citation ids: {duplicates}")

        for label, items, id_attr in (
            ("clause finding", self.clauses, "finding_id"),
            ("risk flag", self.risk_flags, "risk_id"),
            ("abstention", self.abstentions, "abstention_id"),
        ):
            ids = [getattr(i, id_attr) for i in items]
            repeated = sorted({i for i in ids if ids.count(i) > 1})
            if repeated:
                raise ValueError(f"duplicate {label} ids: {repeated}")

        known = set(citation_ids)
        for label, items, id_attr in (
            ("clause finding", self.clauses, "finding_id"),
            ("risk flag", self.risk_flags, "risk_id"),
            ("abstention", self.abstentions, "abstention_id"),
        ):
            for item in items:
                unknown = sorted(set(item.evidence) - known)
                if unknown:
                    raise ValueError(
                        f"{label} {getattr(item, id_attr)!r} references unknown "
                        f"citation ids: {unknown}"
                    )
        return self

    def citation_by_id(self) -> dict[str, CitationV2]:
        return {c.citation_id: c for c in self.citations}
