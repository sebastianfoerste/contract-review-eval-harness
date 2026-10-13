"""Written adjudication between two independent annotations of one candidate cell.

Each cell of the native My Counsel track (one document variant under one playbook) is
annotated twice: blind by a lawyer who is independent of the maintainer, and separately
by the maintainer. This module compares the two filled annotations, writes a blank
adjudication record with one entry per disagreement, and compiles the reference only
once every entry carries a decision and its reasons.

Agreement statistics are descriptive, never a pass mark. Two people who read six
synthetic cells alike have read them alike; that does not make either reading correct.
The output that matters is the disagreement ledger, because each entry is a decision
someone has to make in writing.

Nothing here decides legal adequacy or writes an annotation. The tooling only refuses to
call a reference independently reviewed while a disagreement is open, a record is
unsigned, or the record no longer matches the files it was prepared from. It cannot
verify who the annotators are; the record points to the note that says so.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contract_eval.candidate_annotation import (
    ANNOTATION_SCHEMA,
    HEX64,
    REFERENCE_SCHEMA,
    AnnotatedIssue,
    Annotation,
    reference_provenance,
    resolve_anchors,
)
from contract_eval.candidates import CandidateReference, digest

ADJUDICATION_SCHEMA = "mycounsel.candidate-adjudication.v1"
COMPARISON_SCHEMA = "mycounsel.candidate-comparison.v1"
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256 = re.compile(HEX64)

STATISTICS_LABEL = (
    "Descriptive statistics. They summarise how two readings differ; they do not "
    "establish that either is correct, and they are not a pass mark."
)

# The labels `resolve` writes into the reference's evidence string. An evidence reference
# that carried one of them could put a second, unchecked hash in front of the computed one.
EVIDENCE_MARKERS = ("independent-annotator:", "adjudication-sha256:", "annotation-a-sha256:",
                    "annotation-b-sha256:")

# A length floor cannot tell a reason from filler. It only stops a decision from being
# recorded with none, or with a single word standing in for one.
MIN_REASONING_CHARS = 20
MIN_REASONING_WORDS = 3

Side = Literal["A", "B"]
# LOCATION: the other annotator raised the same playbook entry at another place.
# PRESENCE: the other annotator did not raise that entry at all.
Kind = Literal["LOCATION", "PRESENCE"]
# (playbookReference, paragraph, missingClause): the duplicate key of Annotation.
IssueKey = tuple[str, int | None, bool]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Located(Strict):
    """One playbook entry applied to one place, the unit both annotators answer in."""

    playbookReference: str = Field(min_length=1, max_length=200)
    # Required and nullable: a record states the place explicitly, None for a missing clause.
    paragraph: int | None = Field(ge=0)
    missingClause: bool

    @model_validator(mode="after")
    def place_shape(self) -> "Located":
        if self.missingClause != (self.paragraph is None):
            raise ValueError("a missing clause has no paragraph; an existing-clause issue names exactly one")
        return self

    def key(self) -> IssueKey:
        return self.playbookReference, self.paragraph, self.missingClause


class Disagreement(Located):
    """An issue one annotator raised and the other did not raise at that place."""

    raisedBy: Side
    kind: Kind
    # The raising annotator's own words, carried so the ledger can be read on its own.
    rationale: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class Statistics(Strict):
    label: str
    agreed: int = Field(ge=0)
    onlyInA: int = Field(ge=0)
    onlyInB: int = Field(ge=0)
    # 2 * agreed / (|A| + |B|); None when neither annotator raised an issue.
    positiveAgreement: float | None


class Comparison(Strict):
    schema_: Literal["mycounsel.candidate-comparison.v1"] = Field(alias="schema")
    variant: str
    playbook: str
    documentSha256: str = Field(pattern=HEX64)
    playbookSha256: str = Field(pattern=HEX64)
    annotatorA: str
    annotatorB: str
    agreed: list[Located]
    onlyInA: list[Located]
    onlyInB: list[Located]
    disagreements: list[Disagreement]
    statistics: Statistics
    # Agreed issues that an annotator marked LOW. They need no decision and are shown to
    # the adjudicator all the same.
    lowConfidenceAgreed: list[Located] = Field(default_factory=list)
    # Free text the template could not hold. Outside the key comparison, shown in the ledger.
    uncertaintiesA: str
    uncertaintiesB: str


class Decision(Located):
    raisedBy: Side
    kind: Kind
    # None until the adjudicator decides whether the issue enters the reference.
    decision: Literal["INCLUDE", "EXCLUDE"] | None
    reasoning: str = Field(max_length=5000)

    @model_validator(mode="after")
    def decided_in_writing(self) -> "Decision":
        if self.decision is not None and not _substantive(self.reasoning):
            raise ValueError(
                f"a decided entry needs written reasoning of at least {MIN_REASONING_CHARS} characters "
                f"and {MIN_REASONING_WORDS} words"
            )
        return self


class Adjudication(Strict):
    """The written record for one cell. A blank record validates; `resolve` checks completeness."""

    schema_: Literal["mycounsel.candidate-adjudication.v1"] = Field(alias="schema")
    variant: str
    playbook: str
    documentSha256: str = Field(pattern=HEX64)
    playbookSha256: str = Field(pattern=HEX64)
    # SHA-256 of the two annotation files as returned. A file edited later no longer matches.
    annotationASha256: str = Field(pattern=HEX64)
    annotationBSha256: str = Field(pattern=HEX64)
    annotatorA: str
    annotatorB: str
    decisions: list[Decision] = Field(max_length=400)
    adjudicator: str = Field(max_length=200)
    adjudicatedOn: str
    # Which of the two annotators is independent of the maintainer.
    independentAnnotator: Side | None
    # Where that person's identity and remit are recorded (a dated note, a mail
    # reference). Its presence is not verification of the reviewer.
    reviewerEvidence: str | None = Field(max_length=500)

    @field_validator("adjudicatedOn")
    @classmethod
    def iso_day(cls, value: str) -> str:
        if value and _day(value) is None:
            raise ValueError("adjudicatedOn must be an ISO date")
        return value

    @field_validator("reviewerEvidence")
    @classmethod
    def single_line(cls, value: str | None) -> str | None:
        # The reference carries this inside a one-line evidence string, next to the hashes.
        if value is None:
            return value
        if any(unicodedata.category(char) in ("Cc", "Zl", "Zp") for char in value):
            raise ValueError("reviewerEvidence must be a single line without control characters")
        if any(marker in value.casefold() for marker in EVIDENCE_MARKERS):
            raise ValueError(
                "reviewerEvidence must not contain a label the reference adds itself: "
                + ", ".join(EVIDENCE_MARKERS)
            )
        return value

    @model_validator(mode="after")
    def one_decision_per_issue(self) -> "Adjudication":
        keys = [decision.key() for decision in self.decisions]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate decision for one issue")
        return self


def _substantive(text: str) -> bool:
    words = [word for word in text.split() if any(char.isalpha() for char in word)]
    return len(" ".join(text.split())) >= MIN_REASONING_CHARS and len(words) >= MIN_REASONING_WORDS


def _day(value: str) -> date | None:
    """A calendar day written YYYY-MM-DD, or None. The annotation model checks the shape only."""
    # fullmatch: `$` alone accepts a trailing newline, and fromisoformat alone accepts 20261012.
    if not ISO_DAY.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _person(name: str) -> str:
    """Comparison form of a name. Spacing, case, compatibility forms and invisible
    characters do not make a second person; a different spelling still does."""
    visible = "".join(char for char in unicodedata.normalize("NFKC", name)
                      if unicodedata.category(char) != "Cf")
    return " ".join(visible.split()).casefold()


def _key(issue: AnnotatedIssue) -> IssueKey:
    return issue.playbookReference, issue.paragraph, issue.missingClause


def _order(key: IssueKey) -> tuple[str, int]:
    """Playbook entry first, then the missing clause, then paragraphs in document order."""
    return key[0], -1 if key[1] is None else key[1]


def _place(paragraph: int | None) -> str:
    return "missing clause" if paragraph is None else f"P{paragraph}"


def _label(key: IssueKey) -> str:
    return f"{key[0]} ({_place(key[1])})"


def _located(key: IssueKey) -> dict:
    return {"playbookReference": key[0], "paragraph": key[1], "missingClause": key[2]}


def compare(a: Annotation, b: Annotation) -> Comparison:
    """Compare two annotations of the same cell by issue key.

    An issue key is (playbookReference, paragraph, missingClause). A key both annotators
    wrote is agreed. A key only one wrote is a disagreement of kind LOCATION when the
    other annotator raised the same playbook entry at any other place, and of kind
    PRESENCE when the other annotator did not raise that entry at all. The kind is a
    reading aid for the adjudicator. It pairs nothing: every one-sided key gets its own
    decision, also where two of them look like one clause located differently.

    The statistics are the three counts and positive agreement, 2 * agreed / (|A| + |B|),
    which is None when neither annotator raised an issue. They are descriptive and never
    a pass mark.

    Cohen's kappa is deliberately absent. Kappa needs the number of items both annotators
    could have marked and left unmarked. Here an item is a playbook entry applied to a
    place, a place is any paragraph or "missing", and one entry may be raised at several
    paragraphs. The set of non-issues therefore has no defined size: any count of it (for
    example entries times paragraphs) would be a modelling choice, and a large one would
    push kappa towards 1 however the two readings differ on the few issues that exist.
    """
    if (a.variant, a.playbook) != (b.variant, b.playbook):
        raise ValueError(
            f"annotations describe different cells: {a.variant}/{a.playbook} and {b.variant}/{b.playbook}"
        )
    if a.documentSha256 != b.documentSha256:
        raise ValueError("annotations are bound to different documents")
    if a.playbookSha256 != b.playbookSha256:
        raise ValueError("annotations are bound to different playbooks")
    for binding in ("corpusManifestSha256", "guidelineSha256", "sourceRegisterSha256"):
        # Two readings are only comparable when both annotators had the same instructions,
        # variants, guideline and source register in front of them.
        if getattr(a, binding) != getattr(b, binding):
            raise ValueError(f"annotations were made from different packs ({binding} differs)")
    name_a, name_b = a.annotator.strip(), b.annotator.strip()
    if not _person(name_a) or not _person(name_b):
        raise ValueError("both annotations must name their annotator")
    if _person(name_a) == _person(name_b):
        raise ValueError("both annotations name the same annotator; adjudication needs two different people")

    issues = {"A": {_key(issue): issue for issue in a.issues}, "B": {_key(issue): issue for issue in b.issues}}
    entries = {side: {key[0] for key in raised} for side, raised in issues.items()}
    agreed = sorted(issues["A"].keys() & issues["B"].keys(), key=_order)
    only = {
        "A": sorted(issues["A"].keys() - issues["B"].keys(), key=_order),
        "B": sorted(issues["B"].keys() - issues["A"].keys(), key=_order),
    }
    one_sided = sorted(
        ((key, side) for side in ("A", "B") for key in only[side]),
        key=lambda item: (_order(item[0]), item[1]),
    )
    raised = len(a.issues) + len(b.issues)
    return Comparison.model_validate({
        "schema": COMPARISON_SCHEMA,
        "variant": a.variant,
        "playbook": a.playbook,
        "documentSha256": a.documentSha256,
        "playbookSha256": a.playbookSha256,
        "annotatorA": name_a,
        "annotatorB": name_b,
        "agreed": [_located(key) for key in agreed],
        "onlyInA": [_located(key) for key in only["A"]],
        "onlyInB": [_located(key) for key in only["B"]],
        "disagreements": [{
            **_located(key),
            "raisedBy": side,
            "kind": "LOCATION" if key[0] in entries["B" if side == "A" else "A"] else "PRESENCE",
            "rationale": issues[side][key].rationale,
            "confidence": issues[side][key].confidence,
        } for key, side in one_sided],
        "statistics": {
            "label": STATISTICS_LABEL,
            "agreed": len(agreed),
            "onlyInA": len(only["A"]),
            "onlyInB": len(only["B"]),
            "positiveAgreement": 2 * len(agreed) / raised if raised else None,
        },
        "lowConfidenceAgreed": [_located(key) for key in agreed
                                if "LOW" in (issues["A"][key].confidence, issues["B"][key].confidence)],
        "uncertaintiesA": a.uncertainties,
        "uncertaintiesB": b.uncertainties,
    })


def _require_blind_and_dated(a: Annotation, b: Annotation) -> None:
    for side, annotation in (("A", a), ("B", b)):
        if not annotation.annotatedOn:
            raise ValueError(f"annotation {side} has no annotation date")
        if _day(annotation.annotatedOn) is None:
            raise ValueError(f"annotation {side} is dated {annotation.annotatedOn!r}, which is not a calendar date")
        if annotation.sawModelOutput is not False:
            raise ValueError(
                f"annotation {side} does not attest that no model output was seen (sawModelOutput must be false)"
            )


def _require_sha256(**hashes: str) -> None:
    for name, value in hashes.items():
        # fullmatch: `$` alone would let a trailing newline into the one-line evidence string.
        if not SHA256.fullmatch(value):
            raise ValueError(f"{name} is not a SHA-256 hex digest")
    if len(set(hashes.values())) != len(hashes):
        # Two annotators and an adjudicator never produce identical files.
        raise ValueError(
            "two of " + ", ".join(hashes) + " are identical; each must be the hash of its own file"
        )


def prepare(a: Annotation, b: Annotation, a_sha256: str, b_sha256: str) -> dict:
    """A blank adjudication record: one undecided entry per one-sided issue, nothing signed.

    The record binds the cell, both annotation files by hash and both annotator names.
    Entries are ordered by playbook entry, then place, then raising annotator, so the
    same two annotations always produce the same record. Annotations that could not be
    resolved later (undated, or not attesting that no model output was seen) are refused
    here already: correcting them changes their hash and would strand written decisions.
    Entries and paragraph numbers are checked against the corpus only by `resolve`; run
    `candidate_annotation check` on each annotation first.
    """
    _require_sha256(a_sha256=a_sha256, b_sha256=b_sha256)
    comparison = compare(a, b)
    _require_blind_and_dated(a, b)
    record = {
        "schema": ADJUDICATION_SCHEMA,
        "variant": comparison.variant,
        "playbook": comparison.playbook,
        "documentSha256": comparison.documentSha256,
        "playbookSha256": comparison.playbookSha256,
        "annotationASha256": a_sha256,
        "annotationBSha256": b_sha256,
        "annotatorA": comparison.annotatorA,
        "annotatorB": comparison.annotatorB,
        "decisions": [{
            "playbookReference": item.playbookReference,
            "paragraph": item.paragraph,
            "missingClause": item.missingClause,
            "raisedBy": item.raisedBy,
            "kind": item.kind,
            "decision": None,
            "reasoning": "",
        } for item in comparison.disagreements],
        "adjudicator": "",
        "adjudicatedOn": "",
        "independentAnnotator": None,
        "reviewerEvidence": None,
    }
    Adjudication.model_validate(record)
    return record


def resolve(a: Annotation, b: Annotation, adjudication: Adjudication, corpus_dir: Path,
            a_sha256: str, b_sha256: str, adjudication_sha256: str) -> dict:
    """Compile the adjudicated reference for one cell, or refuse.

    The reference holds every agreed issue and every one-sided issue the adjudicator
    decided to INCLUDE. Paragraph numbers become recorder anchors through the same
    function the single-annotation compiler uses. An agreed issue keeps both annotators'
    wording; an included one keeps the raiser's wording and the adjudication reasoning.
    Excluded issues stay in the record, which the reference binds by hash.

    With no disagreement at all a signed record with an empty decision list is still
    required: independence is a written claim by a named adjudicator, not a by-product
    of two files happening to match.
    """
    _require_sha256(a_sha256=a_sha256, b_sha256=b_sha256, adjudication_sha256=adjudication_sha256)
    # The models are mutable and can be built without validation. Every refusal below,
    # written reasoning included, holds only for what the validators have seen.
    a, b = (Annotation.model_validate(model.model_dump(by_alias=True)) for model in (a, b))
    adjudication = Adjudication.model_validate(adjudication.model_dump(by_alias=True))
    comparison = compare(a, b)
    cell = ("variant", "playbook", "documentSha256", "playbookSha256")
    if any(getattr(adjudication, name) != getattr(comparison, name) for name in cell):
        raise ValueError("adjudication is bound to a different cell than the annotations")
    if (adjudication.annotationASha256, adjudication.annotationBSha256) != (a_sha256, b_sha256):
        if (adjudication.annotationASha256, adjudication.annotationBSha256) == (b_sha256, a_sha256):
            raise ValueError("adjudication binds these annotations in the opposite order; pass them as A then B")
        raise ValueError(
            "adjudication is bound to different annotation files; an annotation changed after the "
            "record was prepared, so prepare a new record"
        )
    if (adjudication.annotatorA.strip(), adjudication.annotatorB.strip()) != (
            comparison.annotatorA, comparison.annotatorB):
        raise ValueError("adjudication names different annotators than the bound annotations")
    _require_blind_and_dated(a, b)

    expected = {item.key(): item for item in comparison.disagreements}
    supplied = {item.key(): item for item in adjudication.decisions}
    missing = sorted(expected.keys() - supplied.keys(), key=_order)
    if missing:
        raise ValueError("no decision for: " + ", ".join(_label(key) for key in missing))
    extra = sorted(supplied.keys() - expected.keys(), key=_order)
    if extra:
        raise ValueError(
            "decision for an issue that is not a current disagreement: " + ", ".join(_label(key) for key in extra)
        )
    for key in sorted(expected, key=_order):
        if (supplied[key].raisedBy, supplied[key].kind) != (expected[key].raisedBy, expected[key].kind):
            raise ValueError(
                f"decision for {_label(key)} misstates who raised it or its kind; expected "
                f"{expected[key].raisedBy} and {expected[key].kind}"
            )
    undecided = [key for key in sorted(supplied, key=_order) if supplied[key].decision is None]
    if undecided:
        raise ValueError("undecided disagreement: " + ", ".join(_label(key) for key in undecided))

    if not _person(adjudication.adjudicator):
        raise ValueError("adjudication names no adjudicator")
    if not adjudication.adjudicatedOn:
        raise ValueError("adjudication has no date")
    if adjudication.independentAnnotator is None:
        raise ValueError("adjudication does not say which annotator is independent of the maintainer")
    if not (adjudication.reviewerEvidence or "").strip():
        raise ValueError("adjudication has no reference to the note that identifies the independent annotator")
    if adjudication.adjudicatedOn < max(a.annotatedOn, b.annotatedOn):
        raise ValueError("adjudication is dated before an annotation it resolves")

    issues = {"A": {_key(issue): issue for issue in a.issues}, "B": {_key(issue): issue for issue in b.issues}}
    # Every issue of both annotations is resolved, not only the ones that enter the
    # reference: an unknown entry or a paragraph outside the document is a defect in the
    # annotation, and excluding it would hide that.
    every = sorted(issues["A"].keys() | issues["B"].keys(), key=_order)
    anchors = dict(zip(every, resolve_anchors(a, corpus_dir, [(key[0], key[1]) for key in every])))

    rationales: dict[IssueKey, str] = {}
    low_confidence = 0
    for item in comparison.agreed:
        key = item.key()
        rationales[key] = "\n".join(
            f"Annotator {side} (confidence {issues[side][key].confidence}): {issues[side][key].rationale}"
            for side in ("A", "B")
        )
        low_confidence += any(issues[side][key].confidence == "LOW" for side in ("A", "B"))
    for key, decision in supplied.items():
        if decision.decision == "INCLUDE":
            raiser = issues[decision.raisedBy][key]
            rationales[key] = (
                f"Annotator {decision.raisedBy} only (confidence {raiser.confidence}): {raiser.rationale}\n"
                f"Adjudication, INCLUDE: {decision.reasoning.strip()}"
            )
            low_confidence += raiser.confidence == "LOW"
    absent = {key[0] for key in rationales if key[2]}
    located = {key[0] for key in rationales if not key[2]}
    if absent & located:
        # The guideline's tie-break holds for the reference as it holds for one annotation:
        # no output could match an entry that is expected both ways.
        raise ValueError(
            "the reference would expect an entry both as a missing clause and at a paragraph: "
            + ", ".join(sorted(absent & located)) + "; include one reading and exclude the other")
    reference = {
        "schema": REFERENCE_SCHEMA,
        "sourceSha256": comparison.documentSha256,
        "playbookSha256": comparison.playbookSha256,
        "status": "INDEPENDENTLY_REVIEWED",
        # Letters, not names: the note behind the evidence reference identifies the person.
        "reviewerEvidence": (
            f"{adjudication.reviewerEvidence.strip()}; "
            f"independent-annotator:{adjudication.independentAnnotator}; "
            f"adjudication-sha256:{adjudication_sha256}; "
            f"annotation-a-sha256:{a_sha256}; annotation-b-sha256:{b_sha256}"
        ),
        "issues": [{
            "playbookReference": key[0],
            "anchorId": anchors[key],
            "missingClause": key[2],
            "rationale": rationales[key],
        } for key in sorted(rationales, key=_order)],
        "provenance": reference_provenance("ADJUDICATED", [a, b], low_confidence),
    }
    CandidateReference.model_validate(reference)
    return reference


def resolve_files(a_path: Path, b_path: Path, adjudication_path: Path, corpus_dir: Path) -> dict:
    """`resolve` from the three files as they lie on disk, hashes taken from their bytes.

    This is the one derivation an experiment repeats to prove that a reference it scores
    against came out of these files and nothing else.
    """
    a, a_sha256 = _read_annotation(a_path)
    b, b_sha256 = _read_annotation(b_path)
    raw = adjudication_path.read_bytes()
    adjudication = Adjudication.model_validate_json(raw.decode("utf-8"))
    return resolve(a, b, adjudication, corpus_dir, a_sha256, b_sha256, digest(raw))


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def _quote(text: str, indent: str = "") -> list[str]:
    return [f"{indent}> {line}".rstrip() for line in text.strip().splitlines()]


def render_ledger(comparison: Comparison) -> str:
    """A disagreement ledger, written for the adjudicator."""
    stats = comparison.statistics
    agreement = ("not defined, neither annotator raised an issue" if stats.positiveAgreement is None
                 else f"{stats.positiveAgreement:.3f}")
    count = len(comparison.disagreements)
    lines = [
        f"# Disagreement ledger: {comparison.variant} / {comparison.playbook}",
        "",
        f"- Document SHA-256: {comparison.documentSha256}",
        f"- Playbook SHA-256: {comparison.playbookSha256}",
        f"- Annotator A: {_cell(comparison.annotatorA)}",
        f"- Annotator B: {_cell(comparison.annotatorB)}",
        "",
        "## Statistics",
        "",
        "Descriptive statistics. They summarise how two readings differ; they do not",
        "establish that either is correct, and they are not a pass mark.",
        "",
        f"- Agreed issues: {stats.agreed}",
        f"- Only annotator A: {stats.onlyInA}",
        f"- Only annotator B: {stats.onlyInB}",
        f"- Positive agreement, 2 x agreed / (|A| + |B|): {agreement}",
        "- Kappa: not computed. The set of non-issues has no defined size here.",
        "",
        f"## Unresolved disagreements: {count}",
        "",
        "Written adjudication is required before a reference can be frozen.",
    ]
    if not count:
        lines += [
            "No issue was raised by one annotator only. A signed adjudication record with an",
            "empty decision list is still required.",
            "",
        ]
    else:
        lines += [
            "Every row needs a decision, INCLUDE or EXCLUDE, with written reasons in the adjudication record.",
            "",
            "LOCATION: the other annotator raised the same playbook entry at another place.",
            "PRESENCE: the other annotator did not raise that entry at all.",
            "",
            "| No. | Playbook entry | Place | Raised by | Kind | Other annotator |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        raised = {
            "A": comparison.agreed + comparison.onlyInA,
            "B": comparison.agreed + comparison.onlyInB,
        }
        for number, item in enumerate(comparison.disagreements, start=1):
            other = "B" if item.raisedBy == "A" else "A"
            places = [_place(entry.paragraph) for entry in raised[other]
                      if entry.playbookReference == item.playbookReference]
            elsewhere = (f"{other} raised it at: {', '.join(places)}" if places
                         else f"{other} did not raise this entry")
            lines.append(
                f"| {number} | {_cell(item.playbookReference)} | {_place(item.paragraph)} "
                f"| {item.raisedBy} | {item.kind} | {elsewhere} |"
            )
        lines += ["", "### Wording of the raising annotator", ""]
        for number, item in enumerate(comparison.disagreements, start=1):
            lines.append(
                f"{number}. {_cell(item.playbookReference)}, {_place(item.paragraph)}, "
                f"annotator {item.raisedBy}, confidence {item.confidence}:"
            )
            lines += _quote(item.rationale, indent="   ")
        lines.append("")
    if comparison.lowConfidenceAgreed:
        lines += [
            "## Agreed issues marked low confidence",
            "",
            "Both annotators raised these, and at least one of them was unsure. No decision is needed.",
            "",
            *[f"- {_cell(item.playbookReference)}, {_place(item.paragraph)}" for item in comparison.lowConfidenceAgreed],
            "",
        ]
    lines += [
        "## Recorded uncertainties",
        "",
        "Free text from the annotations. It lies outside the key comparison; read it before adjudicating.",
        "",
    ]
    for side, text in (("A", comparison.uncertaintiesA), ("B", comparison.uncertaintiesB)):
        if text.strip():
            lines += [f"Annotator {side}:", "", *_quote(text), ""]
        else:
            lines += [f"Annotator {side}: none recorded.", ""]
    return "\n".join(lines)


def write_new(path: Path, text: str) -> None:
    """Create a file, never replace one: an existing record may hold written decisions."""
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError as error:
        raise FileExistsError(
            f"refusing to overwrite {path}: it may hold written decisions; choose another path"
        ) from error


def write_derived(path: Path, text: str) -> None:
    """Write a ledger or a reference. Both can be regenerated, so an older one is replaced.

    An annotation or an adjudication record is a written input and is never replaced:
    one mistyped output path would otherwise destroy the decisions or a hash-bound file.
    """
    if path.exists():
        existing = path.read_bytes()
        # A plain search, not a parse: a record with a stray comma is still a record.
        if any(schema.encode("utf-8") in existing for schema in (ANNOTATION_SCHEMA, ADJUDICATION_SCHEMA)):
            raise FileExistsError(
                f"refusing to overwrite {path}: it is an annotation or an adjudication record; "
                "choose another path"
            )
    path.write_text(text, encoding="utf-8")


def _read_annotation(path: Path) -> tuple[Annotation, str]:
    raw = path.read_bytes()
    return Annotation.model_validate_json(raw.decode("utf-8")), digest(raw)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    compare_cmd = sub.add_parser("compare", help="print or write the disagreement ledger for two annotations")
    prepare_cmd = sub.add_parser("prepare", help="write a blank adjudication record bound to both annotation files")
    resolve_cmd = sub.add_parser("resolve", help="compile the reference from a complete, signed adjudication record")
    for command in (compare_cmd, prepare_cmd, resolve_cmd):
        command.add_argument("a", type=Path, metavar="A.json", help="annotation A")
        command.add_argument("b", type=Path, metavar="B.json", help="annotation B")
    compare_cmd.add_argument("--markdown", type=Path, metavar="OUT",
                             help="write the ledger here instead of printing it; never over an annotation or a record")
    prepare_cmd.add_argument("--out", type=Path, required=True, metavar="FILE",
                             help="new adjudication record; an existing file is never overwritten")
    resolve_cmd.add_argument("adjudication", type=Path, metavar="ADJUDICATION.json")
    resolve_cmd.add_argument("--corpus", type=Path, default=Path("candidates/mycounsel"), metavar="DIR")
    resolve_cmd.add_argument("--out", type=Path, metavar="FILE",
                             help="write the reference here instead of printing it; never over an annotation or a record")
    args = parser.parse_args(argv)

    a, a_sha256 = _read_annotation(args.a)
    b, b_sha256 = _read_annotation(args.b)
    if args.cmd == "compare":
        comparison = compare(a, b)
        if args.markdown:
            write_derived(args.markdown, render_ledger(comparison))
            print(f"Unresolved disagreements: {len(comparison.disagreements)}. Ledger written to {args.markdown}.")
        else:
            print(render_ledger(comparison), end="")
        return
    if args.cmd == "prepare":
        record = prepare(a, b, a_sha256, b_sha256)
        write_new(args.out, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print(f"Wrote a blank adjudication record with {len(record['decisions'])} open decisions to {args.out}.")
        return
    raw = args.adjudication.read_bytes()
    adjudication = Adjudication.model_validate_json(raw.decode("utf-8"))
    reference = resolve(a, b, adjudication, args.corpus, a_sha256, b_sha256, digest(raw))
    text = json.dumps(reference, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        write_derived(args.out, text)
        print(f"Wrote reference to {args.out} ({reference['status']}, {len(reference['issues'])} expected issues).")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
