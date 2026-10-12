"""Native My Counsel candidate evaluation, isolated from ALL_CASES and gold v1.

Rule/anchor matching is a reproducible proxy. It cannot establish whether a
legal explanation or proposed amendment is correct; that needs lawyer review.
"""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
from typing import Literal
from xml.etree import ElementTree
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


XML_ENCODING = re.compile(r"""\s*<\?xml[^>]*?encoding\s*=\s*["']([^"']+)["']""")

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


class Usage(Strict):
    """Provider-reported token counts for one attempt, as the application gateway passes them on.

    Cost is derived later from a verified price table (candidate_budget); a recorder
    never invents it. Absent counts stay None rather than zero.

    `inputTokens` is every input token of the request, cached ones included;
    `cacheReadTokens` is the cached share. `outputTokens` is every billed output token,
    thinking included, whichever way the provider reports it: Anthropic counts thinking
    inside its output figure, Gemini reports thoughts beside its candidate figure and
    the gateway adds the two. `thinkingTokens` is the thinking share where the provider
    states it. The two shares are information and are never added to their totals again.
    """

    # Strict: a JSON true or the text "5" is not a count and must not be read as one.
    inputTokens: int = Field(ge=0, strict=True)
    outputTokens: int = Field(ge=0, strict=True)
    cacheReadTokens: int | None = Field(default=None, ge=0, strict=True)
    thinkingTokens: int | None = Field(default=None, ge=0, strict=True)
    providerRequestId: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def shares_stay_within_their_totals(self) -> "Usage":
        if self.thinkingTokens is not None and self.thinkingTokens > self.outputTokens:
            raise ValueError("thinking tokens are a share of billed output tokens")
        if self.cacheReadTokens is not None and self.cacheReadTokens > self.inputTokens:
            raise ValueError("cached tokens are a share of input tokens")
        return self


def parse_instant(value: str) -> datetime:
    """A timezone-aware ISO 8601 instant, or a refusal. Order checks compare these, never text."""
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{value!r} is not an ISO 8601 date and time") from error
    if instant.tzinfo is None:
        raise ValueError(f"{value!r} carries no time zone")
    try:
        return instant.astimezone(timezone.utc)
    except OverflowError as error:
        raise ValueError(f"{value!r} lies outside the representable range of instants") from error


class Run(Strict):
    mode: Literal["REPLAY", "LIVE"]
    model: str
    promptVersion: str
    codeRevision: str = Field(pattern=r"^[a-f0-9]{40}$")
    workingTreeDirty: bool
    startedAt: str
    elapsedMs: int = Field(ge=0)
    outcome: Literal["COMPLETED", "REFUSED", "FAILED"]
    # Exactly one of the two: real usage, or the reason it is missing. The 2026-10-10
    # replay recordings carry null usage with a reason and stay valid unchanged.
    usage: Usage | None
    usageUnavailableReason: str | None

    @model_validator(mode="after")
    def usage_or_reason(self) -> "Run":
        parse_instant(self.startedAt)
        has_reason = bool(self.usageUnavailableReason and self.usageUnavailableReason.strip())
        if self.usageUnavailableReason is not None and not has_reason:
            raise ValueError("a blank text is not a reason for missing usage")
        if (self.usage is None) != has_reason:
            raise ValueError("an attempt records usage or the reason it is unavailable, never both or neither")
        return self


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
            if anchor.id != anchor_id(self.source.sha256, anchor.paragraph, anchor.text):
                raise ValueError("clause anchor mismatch")
        completed = self.run.outcome == "COMPLETED"
        if completed != (self.findings is not None):
            raise ValueError("attempt outcome does not match native output")
        if (self.validation.status == "NO_OUTPUT") == completed:
            raise ValueError("validation status does not match attempt outcome")
        return self


def recording_digest(artifact: CandidateRun) -> str:
    """Bounded JSON values: sorted object keys, UTF-8, no insignificant spaces.

    This hashes the entire validated recording, including code and attempt data.
    It is not a signature or independent attestation of the producer.
    """
    return digest(json.dumps(artifact.model_dump(by_alias=True),
                             ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class ReferenceIssue(Strict):
    playbookReference: str
    anchorId: str | None
    missingClause: bool
    rationale: str = Field(min_length=1)


class ReferenceProvenance(Strict):
    """What a reference was compiled from. Written by the compilers, never by hand.

    It binds the reference to the material the annotators worked from, beyond the one
    document and playbook: the business instructions and every variant through the
    corpus manifest, the guideline that defined the unit of annotation, and the source
    register. A reference made under another guideline or register is another edition.
    """

    route: Literal["SINGLE_ANNOTATION", "ADJUDICATED"]
    corpusManifestSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    guidelineSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sourceRegisterSha256: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    # Expected issues an annotator marked LOW, and whether free-text doubts were recorded.
    # Both stay visible in every report that scores against this reference.
    lowConfidenceIssues: int = Field(ge=0)
    uncertaintiesRecorded: bool
    # False only when every contributing annotator attested not having seen model output.
    annotatorSawModelOutput: bool


class CandidateReference(Strict):
    schema_: Literal["mycounsel.candidate-reference.v1"] = Field(alias="schema")
    sourceSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    playbookSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["DRAFT", "INDEPENDENTLY_REVIEWED"]
    reviewerEvidence: str | None
    issues: list[ReferenceIssue]
    # Absent only on references written before provenance existed; those stay DRAFT.
    provenance: ReferenceProvenance | None = None

    @model_validator(mode="after")
    def validate_review(self) -> "CandidateReference":
        if self.status == "INDEPENDENTLY_REVIEWED":
            if not (self.reviewerEvidence or "").strip():
                raise ValueError("independent review needs an evidence reference")
            # One annotation is one reading. Only two blind annotations with written
            # adjudication carry the status; the shape alone proves nothing, which is why
            # an experiment re-derives such a reference from its registered source files.
            if self.provenance is None or self.provenance.route != "ADJUDICATED":
                raise ValueError("independent review needs two annotations and written adjudication")
            if self.provenance.annotatorSawModelOutput:
                raise ValueError("an annotator who saw model output cannot support independent review")
        keys = [issue_key(i) for i in self.issues]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate expected issue")
        return self


def digest(value: str | bytes) -> str:
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def anchor_id(source_sha256: str, paragraph: int, text: str) -> str:
    """The recorder's clause anchor: bound to the exact bytes, position and text."""
    return digest(f"{source_sha256}:{paragraph}:{text}")


def issue_key(issue: Finding | ReferenceIssue) -> tuple[str, str | None, bool]:
    return issue.playbookReference, issue.anchorId, issue.missingClause


def verify_document(artifact: CandidateRun, document: bytes) -> None:
    """Verify exact original bytes and text. No extraction to disk or XML entities."""
    if digest(document) != artifact.source.sha256:
        raise ValueError("document hash mismatch")
    if document_paragraphs(document) != [a.text for a in artifact.source.clauses]:
        raise ValueError("recorded clauses differ from original Word text")


def document_paragraphs(document: bytes) -> list[str]:
    """Paragraph texts of a bounded Word package in document order.

    Shared by verification and by the annotation compiler, so a paragraph number an
    annotator writes resolves to the same anchor the recorder produced.
    """
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
        # The guard below reads text. In UTF-16 or UTF-32 the same markup is other bytes and
        # would pass unseen, so only UTF-8 is read at all; Word writes nothing else.
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("document XML is not UTF-8") from error
        declared = XML_ENCODING.match(text)
        if "\x00" in text or (declared and declared.group(1).lower() not in ("utf-8", "utf8")):
            raise ValueError("document XML is not UTF-8")
        if "<!doctype" in text.lower() or "<!entity" in text.lower():
            raise ValueError("unsafe document XML")
        doc = ElementTree.fromstring(raw)
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    if doc.tag != f"{w}document":
        raise ValueError("invalid Word document root")
    return ["".join(n.text or "" for n in p.iter(f"{w}t")) for p in doc.iter(f"{w}p")]


# The application accepts any non-empty passage of the anchored paragraph as a quotation,
# and `quotationValid` mirrors that. A single word or a full stop would then count as
# evidence for an expected issue, so matching additionally asks for a passage of this
# length, or the whole paragraph where the paragraph is shorter.
MIN_QUOTE_CHARS = 20


def _substantive_quote(quote: str, paragraph: str) -> bool:
    collapsed = " ".join(quote.split())
    return bool(collapsed) and (len(collapsed) >= MIN_QUOTE_CHARS or collapsed == " ".join(paragraph.split()))


def findings_digest(artifact: CandidateRun) -> str | None:
    """Fingerprint of what the model returned, without the attempt's time and identity.

    Two repetitions with the same value returned identical findings. That can be an
    honest deterministic model or one output filed twice; a report shows the count and
    lets the reader ask.
    """
    if artifact.findings is None:
        return None
    return digest(json.dumps([f.model_dump() for f in artifact.findings],
                             ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def evaluate_candidates(artifact: CandidateRun, reference: CandidateReference | None = None) -> dict:
    """Recompute evidence validity; never trust the recorder's ACCEPTED flag.

    Matching rule, applied in full here: a finding matches an expected issue when its
    playbook entry, paragraph anchor and missing-clause flag are identical AND the
    finding is matchable. Matchable means the entry exists in the playbook with the
    finding's category, and either the finding is a well-formed missing clause (no
    quotation, no clause anchor, an existing insertion anchor or none) or it quotes a
    substantive passage of its anchored paragraph and carries no insertion anchor. A
    repeated finding matches once; every finding that does not match, repetitions and
    invalid ones included, is a false positive. An attempt without output finds nothing:
    every expected issue is a false negative.
    """
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
        substantive = (
            quote_valid is True and _substantive_quote(finding.quote, anchors[finding.anchorId])
        ) if not finding.missingClause else None
        entry = entries.get(finding.playbookReference)
        reference_valid = entry is not None and entry.category == finding.category
        rows.append({"index": i, "quotationValid": quote_valid, "missingClauseValid": missing_valid,
                     "playbookReferenceValid": reference_valid,
                     "evidenceValid": reference_valid and (missing_valid is True or quote_valid is True),
                     "quotationSubstantive": substantive,
                     "matchable": reference_valid and (missing_valid is True or substantive is True)})
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
        matchable_keys = {issue_key(f) for f, row in zip(findings, rows) if row["matchable"]}
        true_positive = len(matchable_keys & expected_keys)
        expected_entries = {i.playbookReference for i in reference.issues}
        raised_entries = {f.playbookReference for f, row in zip(findings, rows) if row["matchable"]}
        issue_match = {
            "label": "Rule/anchor issue matching proxy; legal reasoning and amendments require lawyer review",
            "referenceStatus": reference.status,
            "referenceRoute": None if reference.provenance is None else reference.provenance.route,
            "independentReviewClaimVerified": False,
            "referenceEvidence": reference.reviewerEvidence,
            "truePositives": true_positive, "falsePositives": len(findings) - true_positive,
            "falseNegatives": len(expected_keys) - true_positive,
            "precision": true_positive / len(findings) if findings else None,
            "recall": true_positive / len(expected_keys) if expected_keys else None,
            # Lenient companion: was the playbook entry raised anywhere, whatever the
            # place? It separates an issue located differently from an issue missed.
            # Counted over distinct entries; repetitions and invalid findings are ignored.
            "entryLevel": {
                "truePositives": len(raised_entries & expected_entries),
                "falsePositives": len(raised_entries - expected_entries),
                "falseNegatives": len(expected_entries - raised_entries),
            },
        }
    unavailable = {"severityAccuracy": "Native output has no severity field",
                   "wholeDocumentClauseCoverage": "Native output has no complete clause inventory",
                   "amendmentQuality": "Requires separate lawyer review"}
    if artifact.run.usage is None:
        unavailable["tokenUsageAndCost"] = artifact.run.usageUnavailableReason
    report = {
        "schema": "mycounsel.candidate-score.v1",
        "recordingSha256": recording_digest(artifact),
        "recordingHashFormat": "utf8-json-sorted-keys-v1",
        "sourceSha256": artifact.source.sha256, "playbookSha256": artifact.playbook.sha256,
        "instructionsSha256": artifact.instructionsSha256,
        "run": artifact.run.model_dump(),
        "attemptMode": artifact.run.mode, "attemptOutcome": artifact.run.outcome,
        "findingCount": len(findings), "duplicateCount": duplicate_count,
        "quotationValid": sum(r["quotationValid"] is True for r in rows),
        "quotationDenominator": sum(r["quotationValid"] is not None for r in rows),
        "trivialQuotationCount": sum(r["quotationValid"] is True and not r["quotationSubstantive"] for r in rows),
        "missingClauseValid": sum(r["missingClauseValid"] is True for r in rows),
        "missingClauseDenominator": sum(r["missingClauseValid"] is not None for r in rows),
        "playbookReferenceValid": sum(r["playbookReferenceValid"] for r in rows),
        # What the application's own validators decide, recomputed here: it passes an
        # output on only when every finding in it is valid, and discards the rest whole.
        "allFindingsValid": artifact.findings is not None and all(r["evidenceValid"] for r in rows),
        "issueMatch": issue_match, "findings": rows,
        "unavailable": unavailable,
    }
    if artifact.run.usage is not None:
        # Token counts only. Money needs the verified price table in candidate_budget,
        # and the committed replay score (usage null) keeps its exact bytes.
        report["usage"] = artifact.run.usage.model_dump()
    return report


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
