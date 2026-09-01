"""Pydantic models for review output and the expected answer set."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["low", "medium", "high"]


class Citation(BaseModel):
    quote: str  # text the model claims appears in the source
    clause_type: str


class RiskFlag(BaseModel):
    clause_type: str
    severity: Severity
    rationale: str


class Clause(BaseModel):
    clause_type: str
    text: str


class Abstention(BaseModel):
    clause_type: str
    reason: str


class ReviewOutput(BaseModel):
    """What an adapter returns for a contract."""

    clauses: list[Clause]
    risk_flags: list[RiskFlag]
    citations: list[Citation]
    abstentions: list[Abstention] = Field(default_factory=list)


class ExpectedAnswer(BaseModel):
    """The gold set stored in expected/<case>.json.

    Unknown fields are rejected. A gold set is the benchmark's ground truth, so a
    misspelled key must fail loudly rather than being silently ignored: an earlier
    `_severity_rationale` key sat in these files unvalidated because Pydantic
    dropped it.
    """

    model_config = ConfigDict(extra="forbid")

    comment: str = ""
    clause_types: list[str]
    risk_flags: dict[str, Severity]
    # One written justification per risk flag, naming why the severity holds and
    # where the position stops being ordinary market practice.
    severity_rationale: dict[str, str] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    # Declared synonyms for the SAME clause of the SAME document: spelling,
    # plural and hyphenation variants, or an equally accurate name for the
    # clause. Structural validation below cannot establish that an alias is a
    # genuine synonym; only human review can. See docs/ANNOTATION_GUIDELINE.md.
    clause_aliases: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_gold_set(self) -> "ExpectedAnswer":
        duplicates = {t for t in self.clause_types if self.clause_types.count(t) > 1}
        if duplicates:
            raise ValueError(f"duplicate clause types: {sorted(duplicates)}")

        canonical = set(self.clause_types)

        unknown_flags = sorted(set(self.risk_flags) - canonical)
        if unknown_flags:
            raise ValueError(f"risk flags for undeclared clause types: {unknown_flags}")

        if self.severity_rationale:
            flagged = set(self.risk_flags)
            documented = set(self.severity_rationale)
            if flagged != documented:
                missing = sorted(flagged - documented)
                extra = sorted(documented - flagged)
                raise ValueError(
                    "severity_rationale must have one entry per risk flag; "
                    f"missing={missing} unexpected={extra}"
                )

        for alias, target in self.clause_aliases.items():
            if target not in canonical:
                raise ValueError(f"alias {alias!r} targets undeclared clause {target!r}")
            if alias in canonical:
                raise ValueError(f"alias {alias!r} shadows a canonical clause type")

        return self
