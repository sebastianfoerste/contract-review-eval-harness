"""A matter: several documents, one client position, and facts that change.

The single-contract cases ask whether a review read one document correctly. A matter
asks what a lawyer is actually asked: across these documents, given what this client
wants, what conflicts, what should be done about each term, and what cannot be
answered yet.

Three things are new relative to a case, and each is data rather than code:

    documents   several per matter, each with a kind and the round it arrived in
    rounds      the matter at successive points in time, each with its own answers
    conditions  which document kinds a system is allowed to see

A condition is how "general baseline" and "matter-specific" are compared. Both run
the same rounds against the same answers; they differ only in what they were shown.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MATTER_SCHEMA = "contract-review-eval.matter.v1"
MATTER_GOLD_SCHEMA = "contract-review-eval.matter-expected.v1"
MATTER_REVIEW_SCHEMA = "contract-review-eval.matter-review.v1"

MATTERS_DIR = Path("matters")

Severity = Literal["low", "medium", "high"]
Task = Literal["conflict", "position", "escalation"]
Action = Literal["accept", "negotiate", "reject", "escalate"]
Split = Literal["dev", "eval"]
DocumentKind = Literal[
    "contract",
    "counterparty_response",
    "negotiation_record",
    "security_questionnaire",
    "client_instruction",
    "playbook",
]
SourceCategory = Literal[
    "law", "regulatory_guidance", "market_practice", "client_playbook", "legal_judgment"
]
AnnotationStatus = Literal["pending", "draft", "candidate", "adjudicated", "frozen"]


class MatterDrift(ValueError):
    """A matter document no longer matches the hash its manifest recorded."""


# --------------------------------------------------------------------------- manifest


class MatterDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    kind: DocumentKind
    # Relative to the repository root, so a matter can reuse the contracts under
    # data/ without copying them. A copy would drift from the certified original.
    path: str
    sha256: str
    introduced_in: str


class MatterRound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_id: str
    title: str
    summary: str
    expected: str = Field(description="Gold answers, relative to the matter directory.")


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition_id: str
    description: str
    visible_kinds: list[DocumentKind] = Field(min_length=1)
    prompt: str = Field(description="Prompt template, relative to the matter directory.")


class MatterContext(BaseModel):
    """Whose matter this is. An answer is only defensible from a position."""

    model_config = ConfigDict(extra="forbid")

    party: str
    counterparty: str
    governing_law: str
    jurisdiction: str
    objective: str
    risk_appetite: Literal["conservative", "balanced", "commercial"]


class Matter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.matter.v1"] = Field(
        default=MATTER_SCHEMA, alias="schema"
    )
    matter_id: str
    title: str
    # Not a flag a real matter could set to false: the type admits only True.
    synthetic: Literal[True]
    context: MatterContext
    documents: list[MatterDocument] = Field(min_length=1)
    rounds: list[MatterRound] = Field(min_length=1)
    conditions: list[Condition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> "Matter":
        for label, ids in (
            ("document", [d.document_id for d in self.documents]),
            ("round", [r.round_id for r in self.rounds]),
            ("condition", [c.condition_id for c in self.conditions]),
        ):
            repeated = sorted({i for i in ids if ids.count(i) > 1})
            if repeated:
                raise ValueError(f"duplicate {label} ids: {repeated}")

        known_rounds = {r.round_id for r in self.rounds}
        orphaned = sorted(
            d.document_id for d in self.documents if d.introduced_in not in known_rounds
        )
        if orphaned:
            raise ValueError(f"documents introduced in an undeclared round: {orphaned}")
        return self

    def round(self, round_id: str) -> MatterRound:
        for candidate in self.rounds:
            if candidate.round_id == round_id:
                return candidate
        raise ValueError(f"unknown round {round_id!r} for matter {self.matter_id!r}")

    def condition(self, condition_id: str) -> Condition:
        for candidate in self.conditions:
            if candidate.condition_id == condition_id:
                return candidate
        raise ValueError(
            f"unknown condition {condition_id!r} for matter {self.matter_id!r}"
        )

    def documents_in_round(self, round_id: str) -> list[MatterDocument]:
        """Everything on the file by this round. Rounds are cumulative, in list order."""
        order = [r.round_id for r in self.rounds]
        cutoff = order.index(self.round(round_id).round_id)
        return [d for d in self.documents if order.index(d.introduced_in) <= cutoff]

    def visible_documents(self, round_id: str, condition_id: str) -> list[MatterDocument]:
        kinds = set(self.condition(condition_id).visible_kinds)
        return [d for d in self.documents_in_round(round_id) if d.kind in kinds]


# ------------------------------------------------------------------------------- gold


class EvidenceSpan(BaseModel):
    """Where an issue lives: a document, raw character offsets, and the text there."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_span(self) -> "EvidenceSpan":
        if self.start >= self.end:
            raise ValueError(f"start {self.start} must be less than end {self.end}")
        return self


class MatterIssue(BaseModel):
    """One thing a competent review of the matter must surface.

    conflict    two or more documents that cannot both be performed or both be true
    position    a term the client must take a stance on, with the stance expected
    escalation  a question that cannot be answered from the file as it stands
    """

    model_config = ConfigDict(extra="forbid")

    issue_id: str
    task: Task
    # Declared per issue and never inferred, so nobody can move an issue between
    # development and evaluation after seeing how a system scored on it.
    split: Split
    title: str
    description: str
    materiality: Severity
    evidence: list[EvidenceSpan] = Field(min_length=1)
    expected_action: Action | None = None
    playbook_rule: str | None = None
    rationale: str = Field(min_length=1)
    source_category: SourceCategory
    source_reference: str | None = None

    @model_validator(mode="after")
    def validate_issue(self) -> "MatterIssue":
        if not self.rationale.strip():
            raise ValueError(f"{self.issue_id}: rationale must contain text")

        documents = {span.document_id for span in self.evidence}
        if self.task == "conflict":
            if len(documents) < 2:
                raise ValueError(
                    f"{self.issue_id}: a conflict needs evidence in at least two "
                    "documents; tension inside one document is a position issue"
                )
            if self.expected_action is not None:
                raise ValueError(
                    f"{self.issue_id}: a conflict carries no expected_action; record "
                    "the stance as a separate position issue"
                )
        elif self.task == "position":
            if self.expected_action is None:
                raise ValueError(f"{self.issue_id}: a position needs an expected_action")
        elif self.expected_action != "escalate":
            raise ValueError(
                f"{self.issue_id}: an escalation issue has expected_action 'escalate'"
            )

        # A conclusion resting on a statute or on the client's own rule must say
        # which one. Judgment and market practice need not, and must not borrow it.
        if (
            self.source_category in ("law", "regulatory_guidance", "client_playbook")
            and not self.source_reference
        ):
            raise ValueError(
                f"{self.issue_id}: source_category {self.source_category!r} requires "
                "a source_reference"
            )
        return self

    def evidence_signature(self) -> tuple[tuple[str, int, int], ...]:
        return tuple(sorted((s.document_id, s.start, s.end) for s in self.evidence))


class GoldStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotator_id: str
    annotation_status: AnnotationStatus
    adjudication_status: Literal["not_started", "in_progress", "complete"]
    legal_position_date: str | None = None


class MatterGold(BaseModel):
    """The answers for one round of one matter."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.matter-expected.v1"] = Field(
        default=MATTER_GOLD_SCHEMA, alias="schema"
    )
    matter_id: str
    round_id: str
    status: GoldStatus
    comment: str = ""
    issues: list[MatterIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_gold(self) -> "MatterGold":
        pending = self.status.annotation_status == "pending"
        if pending and self.issues:
            raise ValueError("a pending gold set must not carry issues")
        if not pending and not self.issues:
            raise ValueError(
                f"gold status {self.status.annotation_status!r} requires at least one issue"
            )

        ids = [i.issue_id for i in self.issues]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"duplicate issue ids: {repeated}")

        # Two issues of one task with identical evidence cannot be told apart by
        # where a finding quoted, so every finding on them would be ambiguous. Where
        # one issue's evidence is contained in another's, the smaller one can never
        # win: quoting it ties, and quoting more goes to the larger.
        for index, issue in enumerate(self.issues):
            evidence = set(issue.evidence_signature())
            for other in self.issues[index + 1 :]:
                if other.task != issue.task:
                    continue
                theirs = set(other.evidence_signature())
                if evidence == theirs:
                    raise ValueError(
                        f"{other.issue_id} and {issue.issue_id} are both {issue.task} "
                        "issues with identical evidence; merge them or anchor them "
                        "differently"
                    )
                if evidence < theirs or theirs < evidence:
                    raise ValueError(
                        f"{other.issue_id} and {issue.issue_id} are both {issue.task} "
                        "issues and the evidence of one is contained in the other's, "
                        "so the smaller could never be credited; give each a passage "
                        "of its own"
                    )
        return self

    @property
    def authored(self) -> bool:
        return self.status.annotation_status != "pending"

    def validate_against_documents(self, texts: dict[str, str]) -> None:
        """Every offset must resolve to the recorded quote in the named document."""
        for issue in self.issues:
            for span in issue.evidence:
                if span.document_id not in texts:
                    raise ValueError(
                        f"{issue.issue_id}: evidence names document "
                        f"{span.document_id!r}, which is not on the file in round "
                        f"{self.round_id!r}"
                    )
                text = texts[span.document_id]
                actual = text[span.start : span.end]
                if actual != span.quote:
                    raise ValueError(
                        f"{issue.issue_id}: {span.document_id}[{span.start}:{span.end}] "
                        f"does not match the recorded quote\n  recorded: {span.quote!r}"
                        f"\n  actual:   {actual!r}"
                    )


# ----------------------------------------------------------------------------- review


class MatterCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(description="Unique id for this citation, for example c1.")
    document_id: str = Field(
        description="The id of the document the quote was copied from, exactly as given."
    )
    quote: str = Field(
        description=(
            "Text copied verbatim from that document, character for character. "
            "Do not paraphrase, reorder or abbreviate."
        )
    )


class ConflictFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    summary: str
    materiality: Severity
    evidence: list[str] = Field(
        default_factory=list,
        description="Citation ids, at least one from each document in conflict.",
    )


class PositionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    summary: str
    action: Action
    materiality: Severity
    playbook_rule: str | None = Field(
        default=None, description="Id of the client rule relied on, if one was provided."
    )
    evidence: list[str] = Field(default_factory=list)


class EscalationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    question: str
    reason: str
    evidence: list[str] = Field(
        default_factory=list,
        description="Citation ids for the passage that makes the gap visible.",
    )


class MatterReview(BaseModel):
    """What an adapter returns for one round of a matter under one condition."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.matter-review.v1"] = Field(
        default=MATTER_REVIEW_SCHEMA, alias="schema"
    )
    conflicts: list[ConflictFinding] = Field(default_factory=list)
    positions: list[PositionFinding] = Field(default_factory=list)
    escalations: list[EscalationFinding] = Field(default_factory=list)
    citations: list[MatterCitation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "MatterReview":
        citation_ids = [c.citation_id for c in self.citations]
        repeated = sorted({i for i in citation_ids if citation_ids.count(i) > 1})
        if repeated:
            raise ValueError(f"duplicate citation ids: {repeated}")

        findings = [*self.conflicts, *self.positions, *self.escalations]
        finding_ids = [f.finding_id for f in findings]
        repeated = sorted({i for i in finding_ids if finding_ids.count(i) > 1})
        if repeated:
            raise ValueError(f"duplicate finding ids: {repeated}")

        known = set(citation_ids)
        for finding in findings:
            unknown = sorted(set(finding.evidence) - known)
            if unknown:
                raise ValueError(
                    f"finding {finding.finding_id!r} references unknown citation ids: "
                    f"{unknown}"
                )
        return self

    def canonical_sha256(self) -> str:
        """Identity of this exact output, so a reviewer's ratings can be bound to it."""
        payload = json.dumps(
            self.model_dump(by_alias=True), sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- loader


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class LoadedMatter:
    matter: Matter
    root: Path
    directory: Path
    texts: dict[str, str]

    def texts_in_round(self, round_id: str) -> dict[str, str]:
        return {
            d.document_id: self.texts[d.document_id]
            for d in self.matter.documents_in_round(round_id)
        }

    def visible_texts(self, round_id: str, condition_id: str) -> dict[str, str]:
        return {
            d.document_id: self.texts[d.document_id]
            for d in self.matter.visible_documents(round_id, condition_id)
        }

    def prompt_template(self, condition_id: str) -> str:
        path = self.directory / self.matter.condition(condition_id).prompt
        return path.read_text(encoding="utf-8")

    def gold(self, round_id: str) -> MatterGold:
        path = self.directory / self.matter.round(round_id).expected
        gold = MatterGold.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if gold.matter_id != self.matter.matter_id or gold.round_id != round_id:
            raise ValueError(
                f"{path}: gold is for {gold.matter_id}/{gold.round_id}, expected "
                f"{self.matter.matter_id}/{round_id}"
            )
        gold.validate_against_documents(self.texts_in_round(round_id))
        return gold


def load_matter(matter_id: str, root: Path = Path(".")) -> LoadedMatter:
    """Load a matter and refuse it if any document has moved since it was recorded.

    Gold offsets and every cited quote are positions in specific bytes. A document
    edited without re-recording its hash would be scored against answers written for
    different text, and nothing downstream could tell.
    """
    directory = root / MATTERS_DIR / matter_id
    manifest = directory / "matter.json"
    if not manifest.is_file():
        raise ValueError(f"unknown matter {matter_id!r}: {manifest} does not exist")
    matter = Matter.model_validate(json.loads(manifest.read_text(encoding="utf-8")))
    if matter.matter_id != matter_id:
        raise ValueError(f"{manifest}: declares matter_id {matter.matter_id!r}")

    texts: dict[str, str] = {}
    drifted: list[str] = []
    for document in matter.documents:
        path = root / document.path
        if not path.is_file():
            raise ValueError(f"{matter_id}: document {document.path} does not exist")
        if file_sha256(path) != document.sha256:
            drifted.append(document.document_id)
        texts[document.document_id] = path.read_text(encoding="utf-8")
    if drifted:
        raise MatterDrift(
            f"{matter_id}: documents changed since their hash was recorded: "
            f"{sorted(drifted)}. Review the change, then run "
            "`python scripts/matter_sync.py --write`."
        )
    return LoadedMatter(matter=matter, root=root, directory=directory, texts=texts)
