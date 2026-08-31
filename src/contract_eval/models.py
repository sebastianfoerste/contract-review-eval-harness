"""Pydantic models for review output and the expected answer set."""

from typing import Literal

from pydantic import BaseModel, Field

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
    """The gold set stored in expected/<case>.json."""

    clause_types: list[str]
    risk_flags: dict[str, str]  # clause_type -> severity
    thresholds: dict[str, float] = Field(default_factory=dict)
    # Declared synonyms for the SAME clause of the SAME document: spelling,
    # plural and hyphenation variants, or an equally accurate name for the
    # clause. Never a way to accept an answer about a different clause.
    clause_aliases: dict[str, str] = Field(default_factory=dict)
