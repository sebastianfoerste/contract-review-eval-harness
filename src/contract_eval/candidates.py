"""Native My Counsel candidate evaluation, isolated from ALL_CASES and gold v1.

Rule/anchor matching is a reproducible proxy. It cannot establish whether a
legal explanation or proposed amendment is correct; that needs lawyer review.
"""

from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from typing import Literal
from xml.etree import ElementTree
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Hash = str
Category = Literal["STATUTORY_REQUIREMENT", "NEGOTIATED_PREFERENCE", "COMMERCIAL_RISK"]


class Anchor(Strict):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    paragraph: int = Field(ge=0)
    text: str
    editable: bool


class Source(Strict):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    filename: str
    clauses: list[Anchor]


class PlaybookEntry(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    category: Category
    requirement: str = Field(min_length=1, max_length=10000)


class Playbook(Strict):
    schema_: Literal["mycounsel.playbook.v1"] = Field(alias="schema")
    entries: list[PlaybookEntry] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> "Playbook":
        if len({e.id for e in self.entries}) != len(self.entries):
            raise ValueError("duplicate playbook entry IDs")
        return self


class BoundPlaybook(Strict):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    instructions: str


class Finding(Strict):
    anchorId: str | None
    insertionAnchorId: str | None = None
    quote: str = Field(max_length=100000)
    missingClause: bool
    category: Category
    explanation: str = Field(min_length=1, max_length=20000)
    proposedAmendment: str = Field(max_length=100000)
    playbookReference: str = Field(min_length=1, max_length=200)


class Run(Strict):
    mode: Literal["REPLAY", "LIVE"]
    model: str
    promptVersion: str
    codeRevision: str = Field(pattern=r"^[a-f0-9]{40}$")
    workingTreeDirty: bool
    startedAt: str
    elapsedMs: int = Field(ge=0)
    outcome: Literal["COMPLETED", "REFUSED", "FAILED"]
    usage: None
    usageUnavailableReason: str


class Validation(Strict):
    status: Literal["ACCEPTED", "REJECTED", "NO_OUTPUT"]
    errorCode: str | None


class CandidateRun(Strict):
    schema_: Literal["mycounsel.candidate-run.v1"] = Field(alias="schema")
    corpusKind: Literal["SYNTHETIC"]
    source: Source
    playbook: BoundPlaybook
    instructions: str
    instructionsSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    run: Run
    findings: list[Finding] | None = Field(max_length=100)
    validation: Validation

    @model_validator(mode="after")
    def validate_binding(self) -> "CandidateRun":
        if digest(self.playbook.instructions) != self.playbook.sha256:
            raise ValueError("playbook hash mismatch")
        Playbook.model_validate_json(self.playbook.instructions)
        if digest(self.instructions) != self.instructionsSha256:
            raise ValueError("business instructions hash mismatch")
        clauses = self.source.clauses
        if [a.paragraph for a in clauses] != list(range(len(clauses))):
            raise ValueError("clause paragraphs must be consecutive in document order")
        for anchor in clauses:
            if anchor.id != digest(f"{self.source.sha256}:{anchor.paragraph}:{anchor.text}"):
                raise ValueError("clause anchor mismatch")
        completed = self.run.outcome == "COMPLETED"
        if completed != (self.findings is not None):
            raise ValueError("attempt outcome does not match native output")
        if (self.validation.status == "NO_OUTPUT") == completed:
            raise ValueError("validation status does not match attempt outcome")
        return self


class ReferenceIssue(Strict):
    playbookReference: str
    anchorId: str | None
    missingClause: bool
    rationale: str = Field(min_length=1)


class CandidateReference(Strict):
    schema_: Literal["mycounsel.candidate-reference.v1"] = Field(alias="schema")
    sourceSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    playbookSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["DRAFT", "INDEPENDENTLY_REVIEWED"]
    reviewerEvidence: str | None
    issues: list[ReferenceIssue]

    @model_validator(mode="after")
    def validate_review(self) -> "CandidateReference":
        if self.status == "INDEPENDENTLY_REVIEWED" and not self.reviewerEvidence:
            raise ValueError("independent review needs an evidence reference")
        keys = [issue_key(i) for i in self.issues]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate expected issue")
        return self


def digest(value: str | bytes) -> str:
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def issue_key(issue: Finding | ReferenceIssue) -> tuple[str, str | None, bool]:
    return issue.playbookReference, issue.anchorId, issue.missingClause


def verify_document(artifact: CandidateRun, document: bytes) -> None:
    """Verify exact original bytes and text. No extraction to disk or XML entities."""
    if digest(document) != artifact.source.sha256:
        raise ValueError("document hash mismatch")
    if len(document) > 20 * 1024 * 1024:
        raise ValueError("document exceeds package limit")
    with ZipFile(BytesIO(document)) as package:
        entries = package.infolist()
        if len(entries) > 1000 or sum(e.file_size for e in entries) > 32 * 1024 * 1024:
            raise ValueError("document exceeds expansion limit")
        names = [e.filename.lower() for e in entries]
        if len(set(names)) != len(names) or any(
            ".." in n or "\\" in n or n.startswith("/") or "\x00" in n for n in names
        ):
            raise ValueError("unsafe document package")
        raw = package.read("word/document.xml")
        if b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
            raise ValueError("unsafe document XML")
        doc = ElementTree.fromstring(raw)
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    if doc.tag != f"{w}document":
        raise ValueError("invalid Word document root")
    texts = ["".join(n.text or "" for n in p.iter(f"{w}t")) for p in doc.iter(f"{w}p")]
    if texts != [a.text for a in artifact.source.clauses]:
        raise ValueError("recorded clauses differ from original Word text")


def evaluate_candidates(artifact: CandidateRun, reference: CandidateReference | None = None) -> dict:
    """Recompute evidence validity; never trust the recorder's ACCEPTED flag."""
    book = Playbook.model_validate_json(artifact.playbook.instructions)
    entries = {entry.id: entry for entry in book.entries}
    anchors = {a.id: a.text for a in artifact.source.clauses}
    findings = artifact.findings or []
    rows = []
    for i, finding in enumerate(findings):
        missing_valid = (
            finding.anchorId is None and finding.quote == "" and
            (finding.insertionAnchorId is None or finding.insertionAnchorId in anchors)
        ) if finding.missingClause else None
        quote_valid = (
            finding.anchorId in anchors and bool(finding.quote) and
            finding.quote in anchors[finding.anchorId] and finding.insertionAnchorId is None
        ) if not finding.missingClause else None
        entry = entries.get(finding.playbookReference)
        reference_valid = entry is not None and entry.category == finding.category
        rows.append({"index": i, "quotationValid": quote_valid, "missingClauseValid": missing_valid,
                     "playbookReferenceValid": reference_valid,
                     "evidenceValid": reference_valid and (missing_valid is True or quote_valid is True)})
    count = Counter(issue_key(f) for f in findings)
    duplicate_count = sum(n - 1 for n in count.values())
    issue_match = None
    if reference is not None:
        if reference.sourceSha256 != artifact.source.sha256 or reference.playbookSha256 != artifact.playbook.sha256:
            raise ValueError("reference is bound to different source or playbook")
        for expected in reference.issues:
            if expected.playbookReference not in entries:
                raise ValueError("reference uses an unknown playbook entry")
            if expected.missingClause != (expected.anchorId is None):
                raise ValueError("reference missing-clause shape is invalid")
            if expected.anchorId is not None and expected.anchorId not in anchors:
                raise ValueError("reference uses an unknown source anchor")
        expected_keys = {issue_key(i) for i in reference.issues}
        valid_keys = {issue_key(f) for f, row in zip(findings, rows) if row["evidenceValid"]}
        true_positive = len(valid_keys & expected_keys)
        issue_match = {
            "label": "Rule/anchor issue matching proxy; legal reasoning and amendments require lawyer review",
            "referenceStatus": reference.status,
            "independentReviewClaimVerified": False,
            "referenceEvidence": reference.reviewerEvidence,
            "truePositives": true_positive, "falsePositives": len(findings) - true_positive,
            "falseNegatives": len(expected_keys) - true_positive,
            "precision": true_positive / len(findings) if findings else None,
            "recall": true_positive / len(expected_keys) if expected_keys else None,
        }
    return {
        "schema": "mycounsel.candidate-score.v1",
        "sourceSha256": artifact.source.sha256, "playbookSha256": artifact.playbook.sha256,
        "attemptMode": artifact.run.mode, "attemptOutcome": artifact.run.outcome,
        "findingCount": len(findings), "duplicateCount": duplicate_count,
        "quotationValid": sum(r["quotationValid"] is True for r in rows),
        "quotationDenominator": sum(r["quotationValid"] is not None for r in rows),
        "missingClauseValid": sum(r["missingClauseValid"] is True for r in rows),
        "missingClauseDenominator": sum(r["missingClauseValid"] is not None for r in rows),
        "playbookReferenceValid": sum(r["playbookReferenceValid"] for r in rows),
        "issueMatch": issue_match, "findings": rows,
        "unavailable": {"severityAccuracy": "Native output has no severity field",
                        "wholeDocumentClauseCoverage": "Native output has no complete clause inventory",
                        "amendmentQuality": "Requires separate lawyer review",
                        "tokenUsageAndCost": artifact.run.usageUnavailableReason},
    }


def comparison_key(artifact: CandidateRun) -> tuple[str, str, str, str]:
    """Only the same inputs and observation mode may be compared."""
    return (artifact.source.sha256, artifact.playbook.sha256,
            artifact.instructionsSha256, artifact.run.mode)


def main() -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    artifact = CandidateRun.model_validate_json(args.run.read_text())
    verify_document(artifact, args.document.read_bytes())
    reference = CandidateReference.model_validate_json(args.reference.read_text()) if args.reference else None
    report = json.dumps(evaluate_candidates(artifact, reference), indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(report)
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
