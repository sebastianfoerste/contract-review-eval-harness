"""Pydantic models for review output and the expected answer set."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["low", "medium", "high"]


class ReviewContext(BaseModel):
    """Whose review this gold set encodes.

    A severity is only defensible relative to a position. An uncapped fee increase is
    high risk for the customer and unremarkable for the provider; an audit exclusion
    reads differently under a regime that mandates the right. Leaving this implicit
    made the gold sets look like statements about the contract rather than statements
    from a party's side of it.
    """

    model_config = ConfigDict(extra="forbid")

    party: str
    governing_law: str
    objective: str
    risk_appetite: Literal["conservative", "balanced", "commercial"]


class Citation(BaseModel):
    quote: str = Field(
        description=(
            "Text copied verbatim from the contract, character for character. "
            "Do not paraphrase, reorder or abbreviate."
        )
    )
    clause_type: str = Field(
        description="snake_case identifier of the clause this quote supports."
    )


class RiskFlag(BaseModel):
    clause_type: str = Field(
        description="snake_case identifier of the clause, for example limitation_of_liability."
    )
    severity: Severity
    rationale: str


class Clause(BaseModel):
    # The schema is the single definition of the response shape, so the naming
    # convention lives here rather than in prose. Without it a structured-output
    # model returns readable labels such as "Definition of Confidential Information",
    # which is a correct review that scores 0.00 against a snake_case gold set.
    clause_type: str = Field(
        description=(
            "snake_case identifier of the clause type, lowercase, words separated by "
            "underscores, no spaces or punctuation. For example: confidentiality, "
            "governing_law, limitation_of_liability."
        )
    )
    text: str = Field(description="One short sentence describing the clause.")


class Abstention(BaseModel):
    clause_type: str = Field(description="snake_case identifier of the affected clause.")
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
    review_context: ReviewContext | None = None
    clause_types: list[str]
    risk_flags: dict[str, Severity]
    # One written justification per risk flag, naming why the severity holds and
    # where the position stops being ordinary market practice.
    severity_rationale: dict[str, str] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    # Declared synonyms for the SAME clause of the SAME document: spelling,
    # plural and hyphenation variants, or an equally accurate name for the
    # clause. Validation below is structural only: it checks that a target is a
    # declared clause type and that an alias does not shadow one. It cannot
    # establish that an alias is a genuine synonym, so mapping `termination`
    # onto `audit_rights` passes every automated check. Only human review
    # establishes semantic equivalence. See docs/ANNOTATION_GUIDELINE.md.
    clause_aliases: dict[str, str] = Field(default_factory=dict)
    # A verbatim phrase locating each clause in the source document. Scoring
    # against these removes the dependence on whatever vocabulary a review used
    # for its labels. Each anchor must occur exactly once in the source; that is
    # checked against the document by scripts/check_clause_anchors.py.
    clause_anchors: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_gold_set(self) -> "ExpectedAnswer":
        duplicates = {t for t in self.clause_types if self.clause_types.count(t) > 1}
        if duplicates:
            raise ValueError(f"duplicate clause types: {sorted(duplicates)}")

        canonical = set(self.clause_types)

        unknown_flags = sorted(set(self.risk_flags) - canonical)
        if unknown_flags:
            raise ValueError(f"risk flags for undeclared clause types: {unknown_flags}")

        # Unconditional. Guarding this on a non-empty severity_rationale let a gold
        # set carry risk flags with no written justification at all, which is the
        # one case the rule exists to prevent.
        flagged = set(self.risk_flags)
        documented = set(self.severity_rationale)
        if flagged != documented:
            missing = sorted(flagged - documented)
            extra = sorted(documented - flagged)
            raise ValueError(
                "severity_rationale must have exactly one entry per risk flag; "
                f"missing={missing} unexpected={extra}"
            )

        blank = sorted(k for k, v in self.severity_rationale.items() if not v.strip())
        if blank:
            raise ValueError(f"severity_rationale entries must not be blank: {blank}")

        if self.clause_anchors:
            anchored = set(self.clause_anchors)
            if anchored != canonical:
                missing = sorted(canonical - anchored)
                extra = sorted(anchored - canonical)
                raise ValueError(
                    "clause_anchors must have one entry per clause type; "
                    f"missing={missing} unexpected={extra}"
                )

        for alias, target in self.clause_aliases.items():
            if target not in canonical:
                raise ValueError(f"alias {alias!r} targets undeclared clause {target!r}")
            if alias in canonical:
                raise ValueError(f"alias {alias!r} shadows a canonical clause type")

        return self
