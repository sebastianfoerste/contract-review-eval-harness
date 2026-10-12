"""One native recording, scored: binding, evidence validity, counts and issue matching.

Expected values are counted by hand from candidates/mycounsel/README.md and the
docstrings of contract_eval.candidates. The pinned hashes were read off the committed
files with shasum and jq, never with the module under test. Every annotator, rationale,
explanation and evidence note below is test text and no legal validation.
"""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pydantic import ValidationError

from contract_eval.candidates import (
    CandidateReference, CandidateRun, Finding, Run, Usage, anchor_id, comparison_key, digest,
    document_paragraphs, evaluate_candidates, findings_digest, issue_key, main, parse_instant,
    recording_digest, verify_document,
)

CORPUS = Path(__file__).resolve().parents[1] / "candidates" / "mycounsel"
REPLAY = CORPUS / "replay-run.json"
SCORE = CORPUS / "replay-score.json"
BASE_DOCUMENT = CORPUS / "ict-base.docx"

# shasum -a 256 of the committed files.
SOURCE_SHA = "08c870e7f7410b37a4c9e6f3aef2039cc10242250bfbe789923b165c429d925e"
CHANGED_SHA = "497b6d3fcfc453e978333bf5d6ce618b3372c8298ccc3cf86cba4630b3556c60"
INJECTION_SHA = "e52547caebdb262cfd72fc4c1dcfa2ca4a7b9d9daf4012a291b6be3c60edc28a"
PLAYBOOK_SHA = "ad974d96506f0b8a6507425dd52cef11dc86bc8a0b59f8f1764b3156dbf7303c"
DORA_PLAYBOOK_SHA = "69ec8f3380afc47fc356c96d8bdefc7ebcaae3213accb0e3f4e456fb09d4ab8d"
# jq -rj .instructions replay-run.json | shasum -a 256
INSTRUCTIONS_SHA = "a93297836440ebbb8cb08d17fb84064a26fca3995a8ebdb697cd9d99b5bf3be0"
# jq -cS . replay-run.json and jq -cS .findings replay-run.json, without the final newline.
RECORDING_SHA = "1891bd4bd1143a0d5012ecc5ed93e4d60e213bc4c53900a15a448ecca2352d57"
FINDINGS_SHA = "1a2386870c50ac51654888194461ec7d731b1e96332933cd971d63aa8defab2b"
# shasum -a 256 of the two characters [] and of the three characters abc.
EMPTY_LIST_SHA = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
ABC_SHA = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

# Paragraph 2 of ict-base.md and the anchor the ZuRecht recorder wrote for it.
FEES_TEXT = ("2. Fees. The annual fee is EUR 120,000, payable quarterly in advance. "
             "The Provider may increase fees by any amount on ten days notice.")
FEES_ANCHOR = "9247a4f892a4d082c5c7ad4d132957fafe1ceffe2a7f9d19d59ab3bf0c917fbd"

# commercial.json, copied by hand.
CATEGORY = {
    "COM-FEES": "NEGOTIATED_PREFERENCE", "COM-RENEWAL": "NEGOTIATED_PREFERENCE",
    "COM-SLA": "COMMERCIAL_RISK", "COM-LIABILITY": "NEGOTIATED_PREFERENCE",
    "COM-SUSPENSION": "COMMERCIAL_RISK", "COM-EXIT": "NEGOTIATED_PREFERENCE",
}

COMMITTED_RUN = {
    "mode": "REPLAY", "model": "hand-authored-replay-fixture",
    "promptVersion": "contracts/candidates/2026-09-11",
    "codeRevision": "041d0157c364f0919ba5227c7159c3d6906507c4", "workingTreeDirty": True,
    "startedAt": "2026-10-10T09:15:41.839Z", "elapsedMs": 1, "outcome": "COMPLETED",
    "usage": None, "usageUnavailableReason": "The application gateway does not expose token usage or cost.",
}
USAGE = {"inputTokens": 5200, "outputTokens": 1800, "cacheReadTokens": 1200,
         "thinkingTokens": 600, "providerRequestId": "test-request-1"}

PROVENANCE = {
    "route": "ADJUDICATED", "corpusManifestSha256": "1" * 64, "guidelineSha256": "2" * 64,
    "sourceRegisterSha256": None, "lowConfidenceIssues": 0, "uncertaintiesRecorded": False,
    "annotatorSawModelOutput": False,
}

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FIGURES = ("findingCount", "duplicateCount", "quotationValid", "quotationDenominator",
           "trivialQuotationCount", "missingClauseValid", "missingClauseDenominator",
           "playbookReferenceValid", "allFindingsValid")
STRICT = ("truePositives", "falsePositives", "falseNegatives", "precision", "recall")


def recording() -> dict:
    """The committed recording as plain data, free to vary in memory."""
    return json.loads(REPLAY.read_text(encoding="utf-8"))


ANCHOR = {clause["paragraph"]: clause["id"] for clause in recording()["source"]["clauses"]}
TEXT = {clause["paragraph"]: clause["text"] for clause in recording()["source"]["clauses"]}


def run() -> CandidateRun:
    return CandidateRun.model_validate(recording())


def text_sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def recorder_anchor(paragraph: int, text: str) -> str:
    """The recorder's anchor written out with hashlib, so no builder leans on the module."""
    return text_sha(f"{SOURCE_SHA}:{paragraph}:{text}")


def finding(entry: str = "COM-FEES", paragraph: int = 2, **changes) -> dict:
    """A located finding that quotes its whole paragraph under the entry's own category."""
    return {
        "anchorId": ANCHOR[paragraph], "insertionAnchorId": None, "quote": TEXT[paragraph],
        "missingClause": False, "category": CATEGORY.get(entry, "NEGOTIATED_PREFERENCE"),
        "explanation": "test explanation, not legal validation", "proposedAmendment": "",
        "playbookReference": entry,
    } | changes


def missing(entry: str = "COM-EXIT", **changes) -> dict:
    """A well-formed missing-clause finding: no quotation and no clause anchor."""
    return finding(entry, anchorId=None, quote="", missingClause=True) | changes


def completed(findings: list[dict], appended: tuple[str, ...] = ()) -> CandidateRun:
    """The committed recording with other findings and, where given, further paragraphs."""
    data = recording()
    data["findings"] = findings
    for text in appended:
        paragraph = len(data["source"]["clauses"])
        data["source"]["clauses"].append(
            {"id": recorder_anchor(paragraph, text), "paragraph": paragraph, "text": text, "editable": True})
    return CandidateRun.model_validate(data)


def without_output(outcome: str) -> CandidateRun:
    data = recording()
    data["run"]["outcome"] = outcome
    data["findings"] = None
    data["validation"] = {"status": "NO_OUTPUT", "errorCode": "TEST_NO_OUTPUT"}
    return CandidateRun.model_validate(data)


def with_run(**changes) -> CandidateRun:
    data = recording()
    data["run"].update(changes)
    return CandidateRun.model_validate(data)


def row(finding_data: dict, appended: tuple[str, ...] = ()) -> dict:
    return evaluate_candidates(completed([finding_data], appended))["findings"][0]


def figures(score: dict) -> dict:
    return {name: score[name] for name in FIGURES}


def expected(entry: str, paragraph: int | None = None) -> dict:
    """One expected issue: located at a paragraph, or a missing clause when none is given."""
    return {"playbookReference": entry, "anchorId": None if paragraph is None else ANCHOR[paragraph],
            "missingClause": paragraph is None, "rationale": "test rationale, not legal validation"}


def reference_data(issues: list[dict], **changes) -> dict:
    return {"schema": "mycounsel.candidate-reference.v1", "sourceSha256": SOURCE_SHA,
            "playbookSha256": PLAYBOOK_SHA, "status": "DRAFT", "reviewerEvidence": None,
            "issues": issues} | changes


def reference(issues: list[dict], **changes) -> CandidateReference:
    return CandidateReference.model_validate(reference_data(issues, **changes))


def issue_match(artifact: CandidateRun, issues: list[dict], **changes) -> dict:
    return evaluate_candidates(artifact, reference(issues, **changes))["issueMatch"]


def strict(match: dict) -> dict:
    return {name: match[name] for name in STRICT}


def word_package(document_xml: bytes, extra: dict[str, bytes] | None = None) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document_xml)
        for name, content in (extra or {}).items():
            package.writestr(name, content)
    return buffer.getvalue()


def word_xml(body: str, prolog: str = "") -> str:
    return f'{prolog}<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'


def cli(monkeypatch, *arguments: object) -> None:
    monkeypatch.setattr(sys, "argv", ["contract_eval.candidates", *map(str, arguments)])
    main()


# --- The committed recording, its score and the corpus manifest ---------------------


def test_committed_score_reproduces_from_the_committed_recording():
    assert evaluate_candidates(run()) == json.loads(SCORE.read_text(encoding="utf-8"))


def test_committed_recording_scores_to_the_hand_counted_figures():
    # The fee clause twice, the same clause under an entry the playbook does not have,
    # and one well-formed missing clause.
    score = evaluate_candidates(run())
    assert figures(score) == {
        "findingCount": 4, "duplicateCount": 1, "quotationValid": 3, "quotationDenominator": 3,
        "trivialQuotationCount": 0, "missingClauseValid": 1, "missingClauseDenominator": 1,
        "playbookReferenceValid": 3, "allFindingsValid": False,
    }
    assert [r["index"] for r in score["findings"]] == [0, 1, 2, 3]
    assert [r["matchable"] for r in score["findings"]] == [True, True, False, True]
    assert score["issueMatch"] is None


def test_score_binds_to_exact_attempt_and_source_revision():
    score = evaluate_candidates(run())
    assert score["schema"] == "mycounsel.candidate-score.v1"
    assert score["recordingSha256"] == RECORDING_SHA
    assert score["recordingHashFormat"] == "utf8-json-sorted-keys-v1"
    assert score["sourceSha256"] == SOURCE_SHA
    assert score["playbookSha256"] == PLAYBOOK_SHA
    assert score["instructionsSha256"] == INSTRUCTIONS_SHA
    assert score["attemptMode"] == "REPLAY"
    assert score["attemptOutcome"] == "COMPLETED"
    assert score["run"] == COMMITTED_RUN


def test_native_shape_does_not_invent_severity_or_clause_inventory():
    assert evaluate_candidates(run())["unavailable"] == {
        "severityAccuracy": "Native output has no severity field",
        "wholeDocumentClauseCoverage": "Native output has no complete clause inventory",
        "amendmentQuality": "Requires separate lawyer review",
        "tokenUsageAndCost": "The application gateway does not expose token usage or cost.",
    }


def test_corpus_manifest_pins_every_variant_and_playbook():
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["corpusKind"] == "SYNTHETIC"
    assert manifest["referenceStatus"] == "DRAFT_NOT_INDEPENDENTLY_REVIEWED"
    assert {d["filename"]: d["sha256"] for d in manifest["documents"]} == {
        "ict-base.docx": SOURCE_SHA, "ict-changed.docx": CHANGED_SHA, "ict-injection.docx": INJECTION_SHA,
    }
    assert [d["variant"] for d in manifest["documents"]] == ["base", "changed", "injection"]
    assert manifest["playbooks"] == {"commercial": PLAYBOOK_SHA, "dora": DORA_PLAYBOOK_SHA}
    for document in manifest["documents"]:
        assert sha256((CORPUS / document["filename"]).read_bytes()).hexdigest() == document["sha256"]
    for name, pinned in manifest["playbooks"].items():
        assert sha256((CORPUS / f"{name}.json").read_bytes()).hexdigest() == pinned


def test_corpus_holds_no_document_or_playbook_outside_the_manifest():
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(p.name for p in CORPUS.glob("*.docx")) == sorted(d["filename"] for d in manifest["documents"])
    playbooks = {p.stem for p in CORPUS.glob("*.json")
                 if json.loads(p.read_text(encoding="utf-8")).get("schema") == "mycounsel.playbook.v1"}
    assert playbooks == {"commercial", "dora"} == set(manifest["playbooks"])


def test_committed_recording_uses_the_manifest_base_document_playbook_and_instructions():
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    data = recording()
    assert data["source"]["sha256"] == SOURCE_SHA
    assert data["source"]["filename"] == "ict-base.docx"
    assert data["playbook"]["instructions"] == (CORPUS / "commercial.json").read_text(encoding="utf-8")
    assert data["instructions"] == manifest["instructions"]
    assert text_sha(manifest["instructions"]) == INSTRUCTIONS_SHA == data["instructionsSha256"]


# --- Hashes, anchors and keys --------------------------------------------------------


def test_digest_is_sha256_of_the_utf8_text_or_of_the_bytes():
    assert digest("abc") == ABC_SHA
    assert digest(b"abc") == ABC_SHA
    # U+00FC is two bytes in UTF-8; hashing the Latin-1 byte would give another value.
    assert digest("ü") == digest(b"\xc3\xbc") != digest(b"\xfc")


def test_anchor_id_reproduces_the_anchor_the_recorder_wrote():
    assert anchor_id(SOURCE_SHA, 2, FEES_TEXT) == FEES_ANCHOR
    assert ANCHOR[2] == FEES_ANCHOR
    assert TEXT[2] == FEES_TEXT


@pytest.mark.parametrize("source, paragraph, text", [
    (CHANGED_SHA, 2, FEES_TEXT),
    (SOURCE_SHA, 3, FEES_TEXT),
    (SOURCE_SHA, 2, FEES_TEXT + " "),
], ids=["other bytes", "other position", "other text"])
def test_anchor_id_is_bound_to_bytes_position_and_text(source, paragraph, text):
    assert anchor_id(source, paragraph, text) != FEES_ANCHOR


def test_issue_key_is_entry_anchor_and_missing_clause_flag():
    assert issue_key(Finding.model_validate(finding())) == ("COM-FEES", FEES_ANCHOR, False)
    assert issue_key(Finding.model_validate(missing(insertionAnchorId=ANCHOR[12]))) == ("COM-EXIT", None, True)


# --- CandidateRun binding ------------------------------------------------------------


def _playbook_text_changed(data):
    data["playbook"]["instructions"] += " "


def _playbook_hash_changed(data):
    data["playbook"]["sha256"] = "0" * 64


def _instructions_changed(data):
    data["instructions"] += " "


def _instructions_hash_changed(data):
    data["instructionsSha256"] = "0" * 64


def _clause_text_changed(data):
    data["source"]["clauses"][0]["text"] = "invented"


def _anchors_of_two_clauses_swapped(data):
    clauses = data["source"]["clauses"]
    clauses[2]["id"], clauses[3]["id"] = clauses[3]["id"], clauses[2]["id"]


def _source_hash_changed(data):
    data["source"]["sha256"] = CHANGED_SHA


def _clauses_reversed(data):
    data["source"]["clauses"].reverse()


def _middle_clause_dropped(data):
    del data["source"]["clauses"][5]


def _first_clause_dropped(data):
    del data["source"]["clauses"][0]


def _completed_without_findings(data):
    data["findings"] = None


def _failed_with_findings(data):
    data["run"]["outcome"] = "FAILED"
    data["validation"] = {"status": "NO_OUTPUT", "errorCode": "TEST_NO_OUTPUT"}


def _refused_with_an_empty_list(data):
    data["run"]["outcome"] = "REFUSED"
    data["findings"] = []
    data["validation"] = {"status": "NO_OUTPUT", "errorCode": "TEST_NO_OUTPUT"}


def _completed_marked_no_output(data):
    data["validation"] = {"status": "NO_OUTPUT", "errorCode": None}


def _failed_marked_accepted(data):
    data["run"]["outcome"] = "FAILED"
    data["findings"] = None
    data["validation"] = {"status": "ACCEPTED", "errorCode": None}


def _refused_marked_rejected(data):
    data["run"]["outcome"] = "REFUSED"
    data["findings"] = None
    data["validation"] = {"status": "REJECTED", "errorCode": "TEST_REJECTED"}


@pytest.mark.parametrize("change, message", [
    (_playbook_text_changed, "playbook hash mismatch"),
    (_playbook_hash_changed, "playbook hash mismatch"),
    (_instructions_changed, "business instructions hash mismatch"),
    (_instructions_hash_changed, "business instructions hash mismatch"),
    (_clause_text_changed, "clause anchor mismatch"),
    (_anchors_of_two_clauses_swapped, "clause anchor mismatch"),
    (_source_hash_changed, "clause anchor mismatch"),
    (_clauses_reversed, "consecutive in document order"),
    (_middle_clause_dropped, "consecutive in document order"),
    (_first_clause_dropped, "consecutive in document order"),
    (_completed_without_findings, "outcome does not match native output"),
    (_failed_with_findings, "outcome does not match native output"),
    (_refused_with_an_empty_list, "outcome does not match native output"),
    (_completed_marked_no_output, "validation status does not match"),
    (_failed_marked_accepted, "validation status does not match"),
    (_refused_marked_rejected, "validation status does not match"),
], ids=lambda value: value.__name__.strip("_") if callable(value) else None)
def test_recording_with_a_broken_binding_is_refused(change, message):
    data = recording()
    change(data)
    with pytest.raises(ValidationError, match=message):
        CandidateRun.model_validate(data)


@pytest.mark.parametrize("outcome", ["FAILED", "REFUSED"])
def test_attempt_without_output_is_a_valid_recording(outcome):
    artifact = without_output(outcome)
    assert artifact.findings is None
    assert artifact.validation.status == "NO_OUTPUT"


@pytest.mark.parametrize("status", ["ACCEPTED", "REJECTED"])
def test_completed_attempt_that_returned_nothing_is_a_valid_recording(status):
    data = recording()
    data["findings"] = []
    data["validation"] = {"status": status, "errorCode": None}
    assert CandidateRun.model_validate(data).findings == []


def _bind_playbook(data: dict, text: str) -> None:
    data["playbook"] = {"sha256": text_sha(text), "instructions": text}


def _entry(identifier: str, category: str = "COMMERCIAL_RISK") -> dict:
    return {"id": identifier, "category": category, "requirement": "test requirement, not legal validation"}


def _playbook(entries: list[dict], schema: str = "mycounsel.playbook.v1") -> str:
    return json.dumps({"schema": schema, "entries": entries})


def test_recording_binds_any_well_formed_playbook_by_its_hash():
    data = recording()
    _bind_playbook(data, _playbook([_entry("TEST-ONE")]))
    assert CandidateRun.model_validate(data).playbook.sha256 == data["playbook"]["sha256"]


@pytest.mark.parametrize("text, message", [
    (_playbook([_entry("TEST-ONE"), _entry("TEST-ONE")]), "duplicate playbook entry IDs"),
    (_playbook([]), "at least 1 item"),
    (_playbook([_entry("TEST-ONE")], schema="mycounsel.playbook.v2"), "mycounsel.playbook.v1"),
    (_playbook([_entry("TEST-ONE", category="LEGAL_OPINION")]), "STATUTORY_REQUIREMENT"),
    (_playbook([_entry("has a space")]), "should match pattern"),
    ("Apply the playbook as you see fit.", "Invalid JSON"),
], ids=["duplicate entry", "no entry", "other schema", "unknown category", "malformed id", "free text"])
def test_correctly_hashed_but_malformed_playbook_is_refused(text, message):
    data = recording()
    _bind_playbook(data, text)
    with pytest.raises(ValidationError, match=message):
        CandidateRun.model_validate(data)


def _corpus_kind_public(data):
    data["corpusKind"] = "PUBLIC"


def _other_schema(data):
    data["schema"] = "mycounsel.candidate-run.v2"


def _score_field_added(data):
    data["score"] = 1.0


def _severity_added_to_a_finding(data):
    data["findings"][0]["severity"] = "HIGH"


def _finding_without_explanation(data):
    data["findings"][0]["explanation"] = ""


def _finding_with_unknown_category(data):
    data["findings"][0]["category"] = "LEGAL_OPINION"


def _malformed_anchor_id(data):
    data["source"]["clauses"][0]["id"] = "not-a-hash"


@pytest.mark.parametrize("change", [
    _corpus_kind_public, _other_schema, _score_field_added, _severity_added_to_a_finding,
    _finding_without_explanation, _finding_with_unknown_category, _malformed_anchor_id,
], ids=lambda value: value.__name__.strip("_"))
def test_recording_outside_the_native_shape_is_refused(change):
    data = recording()
    change(data)
    with pytest.raises(ValidationError):
        CandidateRun.model_validate(data)


def test_recording_holds_at_most_one_hundred_findings():
    score = evaluate_candidates(completed([finding()] * 100))
    assert (score["findingCount"], score["duplicateCount"]) == (100, 99)
    with pytest.raises(ValidationError, match="at most 100 items"):
        completed([finding()] * 101)


# --- The original Word document ------------------------------------------------------


def test_document_verification_accepts_the_recorded_original():
    assert verify_document(run(), BASE_DOCUMENT.read_bytes()) is None


def test_document_verification_refuses_another_document():
    with pytest.raises(ValueError, match="document hash mismatch"):
        verify_document(run(), (CORPUS / "ict-changed.docx").read_bytes())


def test_document_verification_refuses_clause_text_the_document_does_not_contain():
    data = recording()
    data["source"]["clauses"][0]["text"] = "invented"
    data["source"]["clauses"][0]["id"] = recorder_anchor(0, "invented")
    with pytest.raises(ValueError, match="differ from original Word text"):
        verify_document(CandidateRun.model_validate(data), BASE_DOCUMENT.read_bytes())


def test_document_verification_refuses_a_recording_that_left_out_a_paragraph():
    data = recording()
    del data["source"]["clauses"][-1]
    with pytest.raises(ValueError, match="differ from original Word text"):
        verify_document(CandidateRun.model_validate(data), BASE_DOCUMENT.read_bytes())


def test_base_document_reads_as_thirteen_paragraphs_in_document_order():
    paragraphs = document_paragraphs(BASE_DOCUMENT.read_bytes())
    assert len(paragraphs) == 13
    assert paragraphs[0] == "SYNTHETIC EXERCISE. No real parties, service or legal advice. ICT Services Agreement."
    assert paragraphs[2] == FEES_TEXT
    assert paragraphs[12].startswith("12. Notices and changes.")
    assert paragraphs == [TEXT[i] for i in range(13)]


def test_paragraph_text_joins_runs_and_keeps_empty_paragraphs():
    body = "<w:p><w:r><w:t>Split </w:t></w:r><w:r><w:t>across runs.</w:t></w:r></w:p><w:p/>"
    assert document_paragraphs(word_package(word_xml(body).encode())) == ["Split across runs.", ""]


PARAGRAPH = "<w:p><w:r><w:t>Test paragraph.</w:t></w:r></w:p>"
ENTITY_PROLOG = '<!DOCTYPE d [<!ENTITY x "test text injected by an entity">]>'


@pytest.mark.parametrize("package, message", [
    (lambda: word_package(word_xml("<w:p><w:r><w:t>&x;</w:t></w:r></w:p>", ENTITY_PROLOG).encode()),
     "unsafe document XML"),
    (lambda: word_package(word_xml(PARAGRAPH, "<!DOCTYPE d>").encode()), "unsafe document XML"),
    (lambda: word_package(b"<document><p>Test paragraph.</p></document>"), "invalid Word document root"),
    (lambda: word_package(word_xml(PARAGRAPH).encode(), {"../outside.txt": b"x"}), "unsafe document package"),
    (lambda: word_package(word_xml(PARAGRAPH).encode(), {"/absolute.txt": b"x"}), "unsafe document package"),
    (lambda: word_package(word_xml(PARAGRAPH).encode(), {"word\\other.txt": b"x"}), "unsafe document package"),
    (lambda: word_package(word_xml(PARAGRAPH).encode(), {"word/Document.xml": b"x"}), "unsafe document package"),
    (lambda: word_package(word_xml(PARAGRAPH).encode(), {f"part{i}": b"" for i in range(1000)}),
     "exceeds expansion limit"),
    (lambda: word_package(word_xml(PARAGRAPH).encode(), {"padding.bin": b"\0" * (32 * 1024 * 1024)}),
     "exceeds expansion limit"),
    (lambda: b"0" * (20 * 1024 * 1024 + 1), "exceeds package limit"),
], ids=["entity", "doctype", "wrong root", "parent path", "absolute path", "backslash path",
        "names differing by case", "1001 entries", "over 32 MiB unpacked", "over 20 MiB packed"])
def test_unsafe_or_oversized_word_package_is_refused(package, message):
    with pytest.raises(ValueError, match=message):
        document_paragraphs(package())


def test_word_package_with_one_thousand_entries_is_still_read():
    package = word_package(word_xml(PARAGRAPH).encode(), {f"part{i}": b"" for i in range(999)})
    assert document_paragraphs(package) == ["Test paragraph."]


def test_entities_are_refused_whatever_the_xml_encoding():
    xml = word_xml("<w:p><w:r><w:t>&x;</w:t></w:r></w:p>",
                   '<?xml version="1.0" encoding="UTF-16"?>' + ENTITY_PROLOG)
    with pytest.raises(ValueError):
        document_paragraphs(word_package(xml.encode("utf-16")))


# --- Run: start time, usage and its absence ------------------------------------------


@pytest.mark.parametrize("started", [
    "2026-10-10T09:15:41.839Z", "2026-10-10T09:15:41Z", "2026-10-10T11:15:41+02:00",
    "2026-10-10T03:45:41-05:30", "2026-10-10T09:15:41+00:00",
])
def test_timezone_aware_start_time_is_accepted_and_kept_as_recorded(started):
    assert with_run(startedAt=started).run.startedAt == started


@pytest.mark.parametrize("started, message", [
    ("2026-10-10T09:15:41", "carries no time zone"),
    ("2026-10-10T09:15:41.839", "carries no time zone"),
    ("2026-10-10", "carries no time zone"),
    ("garbage", "not an ISO 8601 date and time"),
    ("", "not an ISO 8601 date and time"),
    ("10.10.2026 09:15 UTC", "not an ISO 8601 date and time"),
    ("1760087741", "not an ISO 8601 date and time"),
], ids=["naive", "naive with fraction", "date alone", "garbage", "empty", "german date", "epoch seconds"])
def test_start_time_without_a_zone_or_without_meaning_is_refused(started, message):
    with pytest.raises(ValidationError, match=message):
        with_run(startedAt=started)
    with pytest.raises(ValueError, match=message):
        parse_instant(started)


def test_parse_instant_normalises_to_utc():
    instant = parse_instant("2026-10-10T11:15:41+02:00")
    assert instant.utcoffset() == timedelta(0)
    assert (instant.year, instant.month, instant.day, instant.hour, instant.minute, instant.second) == (
        2026, 10, 10, 9, 15, 41)
    assert parse_instant("2026-10-10T09:15:41.839Z") == datetime(2026, 10, 10, 9, 15, 41, 839000, tzinfo=timezone.utc)
    assert parse_instant("2026-10-10T09:15:41.839Z").isoformat() == "2026-10-10T09:15:41.839000+00:00"


def test_parse_instant_carries_the_date_across_midnight():
    assert parse_instant("2026-10-10T23:30:00-02:00").isoformat() == "2026-10-11T01:30:00+00:00"


def test_instants_order_by_time_where_their_text_orders_the_other_way():
    later, earlier = "2026-10-10T23:30:00-02:00", "2026-10-11T00:30:00+00:00"
    assert later < earlier
    assert parse_instant(later) > parse_instant(earlier)


@pytest.mark.parametrize("started", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
def test_start_time_outside_the_representable_range_is_refused_like_any_other(started):
    with pytest.raises(ValueError):
        parse_instant(started)


def test_recording_carries_usage_without_a_reason():
    artifact = with_run(usage=USAGE, usageUnavailableReason=None)
    assert artifact.run.usage.model_dump() == USAGE
    assert artifact.run.usageUnavailableReason is None


def test_recording_carries_a_reason_without_usage():
    artifact = with_run(usage=None, usageUnavailableReason="test reason: the gateway withheld usage")
    assert artifact.run.usage is None


@pytest.mark.parametrize("usage, reason, message", [
    (USAGE, "test reason: the gateway withheld usage", "never both or neither"),
    (None, None, "never both or neither"),
    (None, "", "blank text is not a reason"),
    (None, " \n\t ", "blank text is not a reason"),
    (USAGE, "   ", "blank text is not a reason"),
], ids=["usage and reason", "neither", "empty reason", "whitespace reason", "usage and blank reason"])
def test_attempt_records_exactly_one_of_usage_and_its_reason(usage, reason, message):
    with pytest.raises(ValidationError, match=message):
        with_run(usage=usage, usageUnavailableReason=reason)


def test_absent_usage_counts_stay_none_rather_than_zero():
    assert Usage.model_validate({"inputTokens": 10, "outputTokens": 5}).model_dump() == {
        "inputTokens": 10, "outputTokens": 5, "cacheReadTokens": None, "thinkingTokens": None,
        "providerRequestId": None,
    }


@pytest.mark.parametrize("usage", [
    {"inputTokens": 100, "outputTokens": 50, "thinkingTokens": 50},
    {"inputTokens": 100, "outputTokens": 50, "cacheReadTokens": 100},
    # Each share is held against its own total: 80 cached is more than the output,
    # 60 thinking is more than the input.
    {"inputTokens": 100, "outputTokens": 50, "cacheReadTokens": 80},
    {"inputTokens": 40, "outputTokens": 70, "thinkingTokens": 60},
], ids=["thinking equals output", "cached equals input", "cached above output", "thinking above input"])
def test_usage_share_within_its_total_is_accepted(usage):
    assert Usage.model_validate(usage).model_dump(exclude_none=True) == usage


@pytest.mark.parametrize("usage, message", [
    ({"inputTokens": 100, "outputTokens": 50, "thinkingTokens": 51}, "thinking tokens are a share"),
    ({"inputTokens": 100, "outputTokens": 50, "cacheReadTokens": 101}, "cached tokens are a share"),
    ({"inputTokens": -1, "outputTokens": 50}, "greater than or equal to 0"),
    ({"inputTokens": 100, "outputTokens": -1}, "greater than or equal to 0"),
    ({"inputTokens": 100, "outputTokens": 50, "cacheReadTokens": -1}, "greater than or equal to 0"),
    ({"inputTokens": 100, "outputTokens": 50, "thinkingTokens": -1}, "greater than or equal to 0"),
    ({"inputTokens": 100, "outputTokens": 50, "costMinorUnits": 3}, "Extra inputs are not permitted"),
    ({"inputTokens": 100}, "Field required"),
    ({"outputTokens": 50}, "Field required"),
    ({"inputTokens": 1.5, "outputTokens": 50}, "valid integer"),
    ({"inputTokens": 100, "outputTokens": 50, "providerRequestId": "x" * 201}, "at most 200 characters"),
], ids=["thinking above output", "cached above input", "negative input", "negative output",
        "negative cached", "negative thinking", "cost field", "no output count", "no input count",
        "fractional count", "overlong request id"])
def test_usage_outside_its_bounds_is_refused(usage, message):
    with pytest.raises(ValidationError, match=message):
        Usage.model_validate(usage)
    with pytest.raises(ValidationError, match=message):
        with_run(usage=usage, usageUnavailableReason=None)


@pytest.mark.parametrize("field, value", [
    ("mode", "DRY_RUN"), ("outcome", "PARTIAL"), ("codeRevision", "041d015"),
    ("codeRevision", "G" * 40), ("elapsedMs", -1), ("costMinorUnits", 3),
], ids=["unknown mode", "unknown outcome", "abbreviated revision", "non-hex revision",
        "negative duration", "cost field"])
def test_run_field_outside_the_recorder_contract_is_refused(field, value):
    with pytest.raises(ValidationError):
        Run.model_validate(COMMITTED_RUN | {field: value})


def test_committed_run_block_is_a_valid_run_on_its_own():
    assert Run.model_validate(COMMITTED_RUN).model_dump() == COMMITTED_RUN


# --- Finding rows: quotations --------------------------------------------------------


def test_whole_paragraph_quotation_is_valid_substantive_and_matchable():
    assert row(finding()) == {
        "index": 0, "quotationValid": True, "missingClauseValid": None, "playbookReferenceValid": True,
        "evidenceValid": True, "quotationSubstantive": True, "matchable": True,
    }


def test_fabricated_quotation_is_not_evidence():
    score = evaluate_candidates(completed([finding(quote="The Provider may never increase the fees.")]))
    assert score["findings"][0] == {
        "index": 0, "quotationValid": False, "missingClauseValid": None, "playbookReferenceValid": True,
        "evidenceValid": False, "quotationSubstantive": False, "matchable": False,
    }
    assert (score["quotationValid"], score["quotationDenominator"]) == (0, 1)
    assert score["trivialQuotationCount"] == 0
    assert score["allFindingsValid"] is False


@pytest.mark.parametrize("quote", [
    "2. fees. The annual fee is EUR 120,000",
    FEES_TEXT + " ",
    "The annual fee is EUR 120.000, payable quarterly",
    "The annual fee is EUR 120,000 payable quarterly in advance",
    "",
], ids=["other case", "one character more", "altered figure", "dropped comma", "empty"])
def test_quotation_that_is_not_a_verbatim_non_empty_passage_is_invalid(quote):
    result = row(finding(quote=quote))
    assert result["quotationValid"] is False
    assert result["evidenceValid"] is False
    assert result["matchable"] is False


def test_quotation_from_another_paragraph_of_the_same_document_is_invalid():
    result = row(finding("COM-FEES", 2, quote=TEXT[3]))
    assert (result["quotationValid"], result["evidenceValid"], result["matchable"]) == (False, False, False)


def test_quoted_finding_that_also_carries_an_insertion_anchor_is_invalid():
    score = evaluate_candidates(completed([finding(insertionAnchorId=ANCHOR[12])]))
    assert score["findings"][0] == {
        "index": 0, "quotationValid": False, "missingClauseValid": None, "playbookReferenceValid": True,
        "evidenceValid": False, "quotationSubstantive": False, "matchable": False,
    }
    assert (score["quotationValid"], score["quotationDenominator"]) == (0, 1)
    assert score["allFindingsValid"] is False


@pytest.mark.parametrize("anchor", [None, "0" * 64], ids=["no anchor", "unknown anchor"])
def test_quoted_finding_without_a_known_clause_anchor_is_invalid(anchor):
    result = row(finding(anchorId=anchor))
    assert (result["quotationValid"], result["quotationSubstantive"], result["matchable"]) == (False, False, False)
    assert result["missingClauseValid"] is None


@pytest.mark.parametrize("quote, raw_length, substantive", [
    ("The annual fee is EUR", 21, True),
    ("The annual fee is EU", 20, True),
    ("The annual fee is E", 19, False),
    # Twenty characters as written, nineteen once the trailing space is collapsed away.
    ("2. Fees. The annual ", 20, False),
    ("Fees.", 5, False),
    (".", 1, False),
    (" ", 1, False),
], ids=["21 characters", "20 characters", "19 characters", "20 with a trailing space",
        "one word", "full stop", "single space"])
def test_quotation_is_substantive_from_twenty_characters_after_whitespace_collapse(quote, raw_length, substantive):
    assert len(quote) == raw_length
    result = row(finding(quote=quote))
    # Validity mirrors the application: every one of these is a verbatim passage.
    assert result["quotationValid"] is True
    assert result["evidenceValid"] is True
    assert result["quotationSubstantive"] is substantive
    assert result["matchable"] is substantive


def test_whitespace_inside_a_quotation_does_not_count_towards_its_length():
    gap = "13. Gap." + " " * 30 + "End of the synthetic gap clause."
    # 37 characters as written; "Gap. End" has eight.
    quote = "Gap." + " " * 30 + "End"
    result = row(finding(anchorId=recorder_anchor(13, gap), quote=quote), appended=(gap,))
    assert len(quote) == 37
    assert (result["quotationValid"], result["quotationSubstantive"], result["matchable"]) == (True, False, False)


def test_whole_paragraph_is_a_substantive_quotation_however_short():
    short = "13. End."
    result = row(finding(anchorId=recorder_anchor(13, short), quote=short), appended=(short,))
    assert (result["quotationValid"], result["quotationSubstantive"], result["matchable"]) == (True, True, True)


def test_part_of_a_short_paragraph_is_a_trivial_quotation():
    short = "13. End."
    score = evaluate_candidates(completed([finding(anchorId=recorder_anchor(13, short), quote="End.")], (short,)))
    assert (score["findings"][0]["quotationValid"], score["findings"][0]["quotationSubstantive"]) == (True, False)
    assert score["trivialQuotationCount"] == 1


def test_whole_paragraph_without_its_outer_whitespace_is_a_substantive_quotation():
    padded = "  13. Spaced.  "
    result = row(finding(anchorId=recorder_anchor(13, padded), quote="13. Spaced."), appended=(padded,))
    assert (result["quotationValid"], result["quotationSubstantive"], result["matchable"]) == (True, True, True)


def test_valid_but_short_quotation_is_counted_as_trivial_and_cannot_match():
    artifact = completed([finding(quote="Fees.")])
    score = evaluate_candidates(artifact, reference([expected("COM-FEES", 2)]))
    assert (score["quotationValid"], score["quotationDenominator"], score["trivialQuotationCount"]) == (1, 1, 1)
    # The application accepts the passage, so the output as a whole stays valid.
    assert score["allFindingsValid"] is True
    assert score["findings"][0]["evidenceValid"] is True
    assert score["findings"][0]["matchable"] is False
    assert strict(score["issueMatch"]) == {
        "truePositives": 0, "falsePositives": 1, "falseNegatives": 1, "precision": 0.0, "recall": 0.0,
    }


def test_fabricated_quotation_on_an_expected_issue_does_not_match():
    artifact = completed([finding(quote="The Provider may never increase the fees.")])
    assert strict(issue_match(artifact, [expected("COM-FEES", 2)])) == {
        "truePositives": 0, "falsePositives": 1, "falseNegatives": 1, "precision": 0.0, "recall": 0.0,
    }


def test_quoted_finding_with_an_insertion_anchor_on_an_expected_issue_does_not_match():
    artifact = completed([finding(insertionAnchorId=ANCHOR[12])])
    assert strict(issue_match(artifact, [expected("COM-FEES", 2)])) == {
        "truePositives": 0, "falsePositives": 1, "falseNegatives": 1, "precision": 0.0, "recall": 0.0,
    }


def test_only_invalid_quotations_stay_out_of_the_trivial_count():
    score = evaluate_candidates(completed([
        finding(quote="The Provider may never increase the fees."),
        finding(insertionAnchorId=ANCHOR[12]),
        finding(quote="Fees."),
        missing(),
    ]))
    assert (score["quotationValid"], score["quotationDenominator"], score["trivialQuotationCount"]) == (1, 3, 1)


# --- Finding rows: missing clauses ---------------------------------------------------


@pytest.mark.parametrize("insertion", [None, ANCHOR[12]], ids=["no insertion anchor", "existing insertion anchor"])
def test_well_formed_missing_clause_is_valid_and_matchable(insertion):
    score = evaluate_candidates(completed([missing(insertionAnchorId=insertion)]))
    assert score["findings"][0] == {
        "index": 0, "quotationValid": None, "missingClauseValid": True, "playbookReferenceValid": True,
        "evidenceValid": True, "quotationSubstantive": None, "matchable": True,
    }
    assert (score["missingClauseValid"], score["missingClauseDenominator"]) == (1, 1)
    assert (score["quotationValid"], score["quotationDenominator"], score["trivialQuotationCount"]) == (0, 0, 0)
    assert score["allFindingsValid"] is True


@pytest.mark.parametrize("changes", [
    {"quote": "invented absence quotation"},
    {"quote": FEES_TEXT},
    {"anchorId": ANCHOR[11]},
    {"insertionAnchorId": "0" * 64},
], ids=["invented quotation", "real quotation", "clause anchor", "unknown insertion anchor"])
def test_malformed_missing_clause_is_invalid_and_cannot_match(changes):
    artifact = completed([missing(**changes)])
    score = evaluate_candidates(artifact, reference([expected("COM-EXIT")]))
    assert score["findings"][0] == {
        "index": 0, "quotationValid": None, "missingClauseValid": False, "playbookReferenceValid": True,
        "evidenceValid": False, "quotationSubstantive": None, "matchable": False,
    }
    assert (score["missingClauseValid"], score["missingClauseDenominator"]) == (0, 1)
    assert score["allFindingsValid"] is False
    assert strict(score["issueMatch"]) == {
        "truePositives": 0, "falsePositives": 1, "falseNegatives": 1, "precision": 0.0, "recall": 0.0,
    }


# --- Finding rows: playbook reference ------------------------------------------------


def test_finding_under_another_category_than_its_entry_is_not_matchable_although_its_quote_is_valid():
    # COM-FEES is a NEGOTIATED_PREFERENCE in commercial.json.
    artifact = completed([finding("COM-FEES", 2, category="COMMERCIAL_RISK")])
    score = evaluate_candidates(artifact, reference([expected("COM-FEES", 2)]))
    assert score["findings"][0] == {
        "index": 0, "quotationValid": True, "missingClauseValid": None, "playbookReferenceValid": False,
        "evidenceValid": False, "quotationSubstantive": True, "matchable": False,
    }
    assert (score["playbookReferenceValid"], score["quotationValid"]) == (0, 1)
    assert score["allFindingsValid"] is False
    assert strict(score["issueMatch"]) == {
        "truePositives": 0, "falsePositives": 1, "falseNegatives": 1, "precision": 0.0, "recall": 0.0,
    }


def test_finding_under_an_unknown_entry_is_not_matchable():
    result = row(finding("UNSUPPORTED-ENTRY", 2))
    assert result == {
        "index": 0, "quotationValid": True, "missingClauseValid": None, "playbookReferenceValid": False,
        "evidenceValid": False, "quotationSubstantive": True, "matchable": False,
    }


def test_missing_clause_under_another_category_than_its_entry_is_not_matchable():
    result = row(missing("COM-EXIT", category="STATUTORY_REQUIREMENT"))
    assert (result["missingClauseValid"], result["playbookReferenceValid"]) == (True, False)
    assert (result["evidenceValid"], result["matchable"]) == (False, False)


def test_recorder_acceptance_flag_is_never_used_in_a_figure():
    data = recording()
    data["validation"] = {"status": "ACCEPTED", "errorCode": None}
    data["findings"][0]["quote"] = "fabricated"
    data["findings"][1]["category"] = "STATUTORY_REQUIREMENT"
    score = evaluate_candidates(CandidateRun.model_validate(data))
    assert score["findings"][0]["quotationValid"] is False
    assert score["findings"][1]["playbookReferenceValid"] is False
    assert (score["quotationValid"], score["playbookReferenceValid"]) == (2, 2)
    assert score["allFindingsValid"] is False


# --- Counts --------------------------------------------------------------------------


def test_duplicate_count_is_the_number_of_repetitions():
    assert evaluate_candidates(completed([finding()] * 3))["duplicateCount"] == 2


def test_duplicate_count_adds_the_repetitions_of_every_repeated_key():
    # COM-FEES three times, the missing clause twice, COM-SLA once: 2 + 1 + 0.
    findings = [finding(), missing(), finding(), finding("COM-SLA", 4), missing(), finding()]
    assert evaluate_candidates(completed(findings))["duplicateCount"] == 3


def test_findings_that_differ_in_entry_anchor_or_missing_flag_are_not_duplicates():
    findings = [finding("COM-FEES", 2), finding("COM-FEES", 3), finding("COM-RENEWAL", 3),
                missing("COM-FEES"), missing("COM-EXIT")]
    assert evaluate_candidates(completed(findings))["duplicateCount"] == 0


def test_finding_repeated_with_other_wording_is_still_a_duplicate():
    findings = [finding(), finding(quote="The Provider may increase fees by any amount",
                                   explanation="test explanation in other words")]
    assert evaluate_candidates(completed(findings))["duplicateCount"] == 1


def test_missing_clause_repeated_with_another_insertion_anchor_is_still_a_duplicate():
    findings = [missing(insertionAnchorId=ANCHOR[12]), missing(insertionAnchorId=ANCHOR[11]), missing()]
    assert evaluate_candidates(completed(findings))["duplicateCount"] == 2


def test_quotation_and_missing_clause_checks_each_keep_their_own_denominator():
    score = evaluate_candidates(completed([
        finding(),
        finding("COM-SLA", 4, quote="The Provider guarantees 99.9 per cent availability."),
        missing("COM-EXIT"),
        missing("COM-SUSPENSION", insertionAnchorId=ANCHOR[10]),
        missing("COM-LIABILITY", quote="invented absence quotation"),
    ]))
    assert figures(score) == {
        "findingCount": 5, "duplicateCount": 0, "quotationValid": 1, "quotationDenominator": 2,
        "trivialQuotationCount": 0, "missingClauseValid": 2, "missingClauseDenominator": 3,
        "playbookReferenceValid": 5, "allFindingsValid": False,
    }


def test_playbook_reference_validity_counts_known_entries_under_their_own_category():
    score = evaluate_candidates(completed([
        finding("COM-FEES", 2),
        finding("COM-SLA", 4),
        finding("COM-SLA", 4, category="NEGOTIATED_PREFERENCE"),
        finding("UNSUPPORTED-ENTRY", 2),
        missing("COM-EXIT", category="COMMERCIAL_RISK"),
        missing("COM-EXIT"),
    ]))
    assert score["playbookReferenceValid"] == 3
    assert [r["playbookReferenceValid"] for r in score["findings"]] == [True, True, False, False, False, True]


def test_all_findings_valid_holds_when_every_finding_is_evidence_valid():
    score = evaluate_candidates(completed([finding(), finding("COM-SLA", 4, quote="uptime"), missing()]))
    assert [r["evidenceValid"] for r in score["findings"]] == [True, True, True]
    assert score["allFindingsValid"] is True


@pytest.mark.parametrize("invalid", [
    finding(quote="The Provider may never increase the fees."),
    finding("UNSUPPORTED-ENTRY", 2),
    finding(category="COMMERCIAL_RISK"),
    missing(quote="invented absence quotation"),
], ids=["fabricated quotation", "unknown entry", "other category", "missing clause with quotation"])
def test_one_invalid_finding_makes_the_whole_output_invalid(invalid):
    assert evaluate_candidates(completed([finding(), invalid, missing()]))["allFindingsValid"] is False


def test_completed_attempt_that_returned_nothing_has_no_invalid_finding():
    score = evaluate_candidates(completed([]))
    assert figures(score) == {
        "findingCount": 0, "duplicateCount": 0, "quotationValid": 0, "quotationDenominator": 0,
        "trivialQuotationCount": 0, "missingClauseValid": 0, "missingClauseDenominator": 0,
        "playbookReferenceValid": 0, "allFindingsValid": True,
    }
    assert score["findings"] == []


@pytest.mark.parametrize("outcome", ["FAILED", "REFUSED"])
def test_attempt_without_output_reports_zero_counts_and_no_valid_output(outcome):
    score = evaluate_candidates(without_output(outcome))
    assert score["attemptOutcome"] == outcome
    assert figures(score) == {
        "findingCount": 0, "duplicateCount": 0, "quotationValid": 0, "quotationDenominator": 0,
        "trivialQuotationCount": 0, "missingClauseValid": 0, "missingClauseDenominator": 0,
        "playbookReferenceValid": 0, "allFindingsValid": False,
    }
    assert score["findings"] == []
    assert score["issueMatch"] is None


# --- Issue matching against a reference ----------------------------------------------


def test_duplicates_and_unknown_rules_cannot_inflate_precision():
    # Committed recording: COM-FEES twice, an unknown entry, COM-EXIT missing.
    match = issue_match(run(), [expected("COM-FEES", 2), expected("COM-EXIT")])
    assert strict(match) == {
        "truePositives": 2, "falsePositives": 2, "falseNegatives": 0, "precision": 0.5, "recall": 1.0,
    }
    assert match["entryLevel"] == {"truePositives": 2, "falsePositives": 0, "falseNegatives": 0}


def test_mixed_attempt_scores_to_the_hand_counted_matches():
    artifact = completed([
        finding("COM-FEES", 2),                                       # 0 matches
        finding("COM-FEES", 2),                                       # 1 repetition of 0
        finding("COM-SLA", 4, quote="The Provider guarantees 99.9 per cent availability."),  # 2 fabricated
        missing("COM-EXIT", insertionAnchorId=ANCHOR[12]),            # 3 matches
        finding("COM-LIABILITY", 10),                                 # 4 right entry, wrong paragraph
        finding("COM-RENEWAL", 3),                                    # 5 valid, not expected
        finding("UNSUPPORTED-ENTRY", 2),                              # 6 unknown entry
        finding("COM-SUSPENSION", 10, quote="10. Suspension."),       # 7 valid, fifteen characters
    ])
    score = evaluate_candidates(artifact, reference([
        expected("COM-FEES", 2), expected("COM-SLA", 4), expected("COM-EXIT"),
        expected("COM-LIABILITY", 9), expected("COM-SUSPENSION", 10),
    ]))
    assert [r["matchable"] for r in score["findings"]] == [True, True, False, True, True, True, False, False]
    assert figures(score) == {
        "findingCount": 8, "duplicateCount": 1, "quotationValid": 6, "quotationDenominator": 7,
        "trivialQuotationCount": 1, "missingClauseValid": 1, "missingClauseDenominator": 1,
        "playbookReferenceValid": 7, "allFindingsValid": False,
    }
    # Two of five expected issues found; the other six findings are false positives.
    assert strict(score["issueMatch"]) == {
        "truePositives": 2, "falsePositives": 6, "falseNegatives": 3, "precision": 0.25, "recall": 0.4,
    }
    # Raised by matchable findings: FEES, EXIT, LIABILITY, RENEWAL. Expected: FEES, SLA,
    # EXIT, LIABILITY, SUSPENSION.
    assert score["issueMatch"]["entryLevel"] == {"truePositives": 3, "falsePositives": 1, "falseNegatives": 2}


def test_repeated_finding_matches_once_and_its_repetitions_are_false_positives():
    match = issue_match(completed([finding()] * 3), [expected("COM-FEES", 2)])
    assert strict(match) == {
        "truePositives": 1, "falsePositives": 2, "falseNegatives": 0, "precision": 1 / 3, "recall": 1.0,
    }


def test_every_finding_that_did_not_match_is_a_false_positive():
    artifact = completed([
        finding("COM-FEES", 2),
        finding("COM-FEES", 2),
        finding("COM-SLA", 4, quote="The Provider guarantees 99.9 per cent availability."),
        finding("UNSUPPORTED-ENTRY", 2),
        missing("COM-EXIT", quote="invented absence quotation"),
    ])
    match = issue_match(artifact, [expected("COM-FEES", 2)])
    assert strict(match) == {
        "truePositives": 1, "falsePositives": 4, "falseNegatives": 0, "precision": 0.2, "recall": 1.0,
    }


def test_expected_issue_is_found_when_one_of_its_repetitions_is_matchable():
    artifact = completed([finding(quote="Fees."), finding()])
    assert strict(issue_match(artifact, [expected("COM-FEES", 2)])) == {
        "truePositives": 1, "falsePositives": 1, "falseNegatives": 0, "precision": 0.5, "recall": 1.0,
    }


def test_finding_must_agree_with_the_expected_issue_in_entry_anchor_and_missing_flag():
    artifact = completed([
        finding("COM-FEES", 3),          # expected entry at another paragraph
        finding("COM-RENEWAL", 2),       # expected paragraph under another entry
        missing("COM-FEES"),             # expected entry reported as missing
    ])
    match = issue_match(artifact, [expected("COM-FEES", 2)])
    assert strict(match) == {
        "truePositives": 0, "falsePositives": 3, "falseNegatives": 1, "precision": 0.0, "recall": 0.0,
    }


@pytest.mark.parametrize("insertion", [None, ANCHOR[11], ANCHOR[12]],
                         ids=["no insertion anchor", "after paragraph 11", "after paragraph 12"])
def test_missing_clause_matches_whatever_its_insertion_anchor(insertion):
    match = issue_match(completed([missing(insertionAnchorId=insertion)]), [expected("COM-EXIT")])
    assert strict(match) == {
        "truePositives": 1, "falsePositives": 0, "falseNegatives": 0, "precision": 1.0, "recall": 1.0,
    }


def test_precision_is_none_when_the_attempt_returned_no_findings():
    match = issue_match(completed([]), [expected("COM-FEES", 2), expected("COM-EXIT")])
    assert strict(match) == {
        "truePositives": 0, "falsePositives": 0, "falseNegatives": 2, "precision": None, "recall": 0.0,
    }


def test_recall_is_none_against_an_empty_reference():
    match = issue_match(run(), [])
    assert strict(match) == {
        "truePositives": 0, "falsePositives": 4, "falseNegatives": 0, "precision": 0.0, "recall": None,
    }
    assert match["entryLevel"] == {"truePositives": 0, "falsePositives": 2, "falseNegatives": 0}


@pytest.mark.parametrize("outcome", ["FAILED", "REFUSED"])
def test_attempt_without_output_misses_every_expected_issue(outcome):
    artifact = without_output(outcome)
    score = evaluate_candidates(artifact, reference([
        expected("COM-FEES", 2), expected("COM-SLA", 4), expected("COM-EXIT"),
    ]))
    assert strict(score["issueMatch"]) == {
        "truePositives": 0, "falsePositives": 0, "falseNegatives": 3, "precision": None, "recall": 0.0,
    }
    assert score["issueMatch"]["entryLevel"] == {"truePositives": 0, "falsePositives": 0, "falseNegatives": 3}
    assert score["allFindingsValid"] is False
    assert score["findingCount"] == 0


def test_attempt_without_output_against_an_empty_reference_has_neither_precision_nor_recall():
    match = issue_match(without_output("FAILED"), [])
    assert strict(match) == {
        "truePositives": 0, "falsePositives": 0, "falseNegatives": 0, "precision": None, "recall": None,
    }


def test_entry_level_separates_an_issue_located_elsewhere_from_an_issue_missed():
    artifact = completed([finding("COM-FEES", 3)])
    match = issue_match(artifact, [expected("COM-FEES", 2), expected("COM-SLA", 4)])
    assert strict(match) == {
        "truePositives": 0, "falsePositives": 1, "falseNegatives": 2, "precision": 0.0, "recall": 0.0,
    }
    assert match["entryLevel"] == {"truePositives": 1, "falsePositives": 0, "falseNegatives": 1}


def test_entry_level_counts_each_entry_once():
    artifact = completed([finding("COM-FEES", 2), finding("COM-FEES", 2), finding("COM-FEES", 3),
                          finding("COM-RENEWAL", 3), finding("COM-RENEWAL", 2)])
    match = issue_match(artifact, [expected("COM-FEES", 2), expected("COM-FEES", 3), expected("COM-SLA", 4)])
    assert strict(match) == {
        "truePositives": 2, "falsePositives": 3, "falseNegatives": 1, "precision": 0.4, "recall": 2 / 3,
    }
    # Entries raised: FEES, RENEWAL. Entries expected: FEES, SLA.
    assert match["entryLevel"] == {"truePositives": 1, "falsePositives": 1, "falseNegatives": 1}


def test_entry_level_ignores_findings_that_are_not_matchable():
    artifact = completed([
        finding("COM-SLA", 4, quote="The Provider guarantees 99.9 per cent availability."),
        finding("COM-FEES", 2, quote="Fees."),
        finding("COM-RENEWAL", 3, category="COMMERCIAL_RISK"),
        finding("UNSUPPORTED-ENTRY", 2),
        missing("COM-EXIT", quote="invented absence quotation"),
    ])
    match = issue_match(artifact, [expected("COM-SLA", 4), expected("COM-FEES", 2)])
    assert match["entryLevel"] == {"truePositives": 0, "falsePositives": 0, "falseNegatives": 2}
    assert strict(match) == {
        "truePositives": 0, "falsePositives": 5, "falseNegatives": 2, "precision": 0.0, "recall": 0.0,
    }


def _reference_for_another_document(data):
    data["sourceSha256"] = CHANGED_SHA


def _reference_for_another_playbook(data):
    data["playbookSha256"] = DORA_PLAYBOOK_SHA


def _reference_with_an_unknown_entry(data):
    data["issues"][0]["playbookReference"] = "DORA-LOCATIONS"


def _reference_with_an_unknown_anchor(data):
    data["issues"][0]["anchorId"] = "0" * 64


def _missing_clause_with_an_anchor(data):
    data["issues"][0]["missingClause"] = True


def _located_issue_without_an_anchor(data):
    data["issues"][1]["missingClause"] = False


REFERENCE_REFUSALS = [
    (_reference_for_another_document, "different source or playbook"),
    (_reference_for_another_playbook, "different source or playbook"),
    (_reference_with_an_unknown_entry, "unknown playbook entry"),
    (_reference_with_an_unknown_anchor, "unknown source anchor"),
    (_missing_clause_with_an_anchor, "missing-clause shape is invalid"),
    (_located_issue_without_an_anchor, "missing-clause shape is invalid"),
]


@pytest.mark.parametrize("change, message", REFERENCE_REFUSALS,
                         ids=lambda value: value.__name__.strip("_") if callable(value) else None)
def test_reference_that_does_not_fit_the_recording_is_refused(change, message):
    data = reference_data([expected("COM-FEES", 2), expected("COM-EXIT")])
    change(data)
    with pytest.raises(ValueError, match=message):
        evaluate_candidates(run(), CandidateReference.model_validate(data))


@pytest.mark.parametrize("change, message", REFERENCE_REFUSALS,
                         ids=lambda value: value.__name__.strip("_") if callable(value) else None)
def test_reference_checks_apply_to_an_attempt_without_output_too(change, message):
    data = reference_data([expected("COM-FEES", 2), expected("COM-EXIT")])
    change(data)
    with pytest.raises(ValueError, match=message):
        evaluate_candidates(without_output("FAILED"), CandidateReference.model_validate(data))


def test_issue_match_is_labelled_as_a_proxy_that_needs_lawyer_review():
    label = issue_match(run(), [expected("COM-FEES", 2)])["label"]
    assert "proxy" in label
    assert "require lawyer review" in label


def test_independent_review_claim_is_reported_but_never_as_verified():
    match = issue_match(run(), [expected("COM-FEES", 2)], status="INDEPENDENTLY_REVIEWED",
                        reviewerEvidence="test evidence note, no review took place", provenance=PROVENANCE)
    assert match["referenceStatus"] == "INDEPENDENTLY_REVIEWED"
    assert match["referenceRoute"] == "ADJUDICATED"
    assert match["referenceEvidence"] == "test evidence note, no review took place"
    assert match["independentReviewClaimVerified"] is False


def test_draft_reference_is_reported_as_draft_and_unverified():
    match = issue_match(run(), [expected("COM-FEES", 2)])
    assert match["referenceStatus"] == "DRAFT"
    assert match["referenceEvidence"] is None
    assert match["independentReviewClaimVerified"] is False


@pytest.mark.parametrize("provenance, route", [
    (None, None),
    (PROVENANCE | {"route": "SINGLE_ANNOTATION"}, "SINGLE_ANNOTATION"),
    (PROVENANCE, "ADJUDICATED"),
], ids=["no provenance", "single annotation", "adjudicated"])
def test_reference_route_reflects_the_provenance(provenance, route):
    assert issue_match(run(), [expected("COM-FEES", 2)], provenance=provenance)["referenceRoute"] == route


# --- CandidateReference --------------------------------------------------------------


def test_adjudicated_blind_reference_with_evidence_may_claim_independent_review():
    gold = reference([expected("COM-FEES", 2)], status="INDEPENDENTLY_REVIEWED",
                     reviewerEvidence="test evidence note, no review took place", provenance=PROVENANCE)
    assert gold.status == "INDEPENDENTLY_REVIEWED"
    assert gold.provenance.route == "ADJUDICATED"


@pytest.mark.parametrize("changes, message", [
    ({"reviewerEvidence": None}, "needs an evidence reference"),
    ({"reviewerEvidence": ""}, "needs an evidence reference"),
    ({"provenance": None}, "two annotations and written adjudication"),
    ({"provenance": PROVENANCE | {"route": "SINGLE_ANNOTATION"}}, "two annotations and written adjudication"),
    ({"provenance": PROVENANCE | {"annotatorSawModelOutput": True}}, "saw model output"),
], ids=["no evidence", "empty evidence", "no provenance", "single annotation", "annotator saw model output"])
def test_independent_review_claim_without_its_support_is_refused(changes, message):
    claim = {"status": "INDEPENDENTLY_REVIEWED", "reviewerEvidence": "test evidence note, no review took place",
             "provenance": PROVENANCE} | changes
    with pytest.raises(ValidationError, match=message):
        reference([expected("COM-FEES", 2)], **claim)


def test_blank_reviewer_evidence_cannot_support_independent_review():
    with pytest.raises(ValidationError):
        reference([expected("COM-FEES", 2)], status="INDEPENDENTLY_REVIEWED", reviewerEvidence=" \n\t ",
                  provenance=PROVENANCE)


def test_draft_reference_without_provenance_stays_valid():
    data = reference_data([expected("COM-FEES", 2), expected("COM-EXIT")])
    assert "provenance" not in data
    gold = CandidateReference.model_validate(data)
    assert gold.status == "DRAFT"
    assert gold.provenance is None


@pytest.mark.parametrize("provenance", [
    PROVENANCE | {"route": "SINGLE_ANNOTATION"},
    PROVENANCE | {"annotatorSawModelOutput": True},
    PROVENANCE | {"sourceRegisterSha256": "3" * 64, "lowConfidenceIssues": 2, "uncertaintiesRecorded": True},
], ids=["single annotation", "annotator saw model output", "with source register and doubts"])
def test_draft_reference_keeps_whatever_provenance_it_was_compiled_from(provenance):
    assert reference([], provenance=provenance).provenance.model_dump() == provenance


@pytest.mark.parametrize("changes", [
    {"route": "PEER_REVIEWED"},
    {"corpusManifestSha256": "1" * 63},
    {"guidelineSha256": "G" * 64},
    {"sourceRegisterSha256": "short"},
    {"lowConfidenceIssues": -1},
    {"annotatorName": "Test Annotator A"},
], ids=["unknown route", "short manifest hash", "non-hex guideline hash", "malformed register hash",
        "negative low-confidence count", "annotator name"])
def test_malformed_provenance_is_refused(changes):
    with pytest.raises(ValidationError):
        reference([], provenance=PROVENANCE | changes)


def test_provenance_must_state_the_source_register_even_when_there_is_none():
    without = {key: value for key, value in PROVENANCE.items() if key != "sourceRegisterSha256"}
    with pytest.raises(ValidationError, match="sourceRegisterSha256"):
        reference([], provenance=without)


def test_duplicate_expected_issue_is_refused():
    with pytest.raises(ValidationError, match="duplicate expected issue"):
        reference([expected("COM-FEES", 2), expected("COM-EXIT"), expected("COM-FEES", 2)])
    with pytest.raises(ValidationError, match="duplicate expected issue"):
        reference([expected("COM-EXIT"), expected("COM-EXIT") | {"rationale": "test rationale in other words"}])


def test_one_entry_may_be_expected_at_two_paragraphs_and_as_missing():
    gold = reference([expected("COM-FEES", 2), expected("COM-FEES", 3), expected("COM-FEES")])
    assert len(gold.issues) == 3


@pytest.mark.parametrize("changes", [
    {"status": "LAWYER_APPROVED"}, {"schema": "mycounsel.candidate-reference.v2"},
    {"sourceSha256": "08c870e7"}, {"playbookSha256": "AD974D96" * 8}, {"annotator": "Test Annotator A"},
], ids=["unknown status", "other schema", "abbreviated hash", "upper-case hash", "extra field"])
def test_reference_outside_its_shape_is_refused(changes):
    with pytest.raises(ValidationError):
        reference([expected("COM-FEES", 2)], **changes)


@pytest.mark.parametrize("changes", [{"rationale": ""}, {"severity": "HIGH"}],
                         ids=["no rationale", "severity field"])
def test_expected_issue_outside_its_shape_is_refused(changes):
    with pytest.raises(ValidationError):
        reference([expected("COM-FEES", 2) | changes])


# --- Digests and the comparison key --------------------------------------------------


def test_recording_digest_is_sha256_of_the_sorted_compact_json():
    assert recording_digest(run()) == RECORDING_SHA


def test_findings_digest_of_the_committed_recording_is_sha256_of_its_findings():
    assert findings_digest(run()) == FINDINGS_SHA


def test_digests_hash_text_outside_ascii_as_utf8_and_not_as_escapes():
    # Both values from jq -cS with the changed field, piped to shasum without the newline.
    data = recording()
    data["run"]["model"] = "test-model-ü"
    assert recording_digest(CandidateRun.model_validate(data)) == (
        "52e6f4d96a6721d02a0c827c3fb2225b9e81eab3d09350fa7c66cae76e422705")
    data = recording()
    data["findings"][0]["explanation"] = "test explanation with an umlaut: Prüfung"
    assert findings_digest(CandidateRun.model_validate(data)) == (
        "7dca25fd57784c0c061924f0fc464cdd708b072296b383886f0f8176d139ee1d")


def test_two_recordings_that_differ_only_in_start_time_share_a_findings_digest():
    first, second = run(), with_run(startedAt="2026-10-10T09:15:42.000Z")
    assert findings_digest(first) == findings_digest(second) == FINDINGS_SHA
    assert recording_digest(first) != recording_digest(second)


RUN_CHANGES = [
    {"mode": "LIVE"}, {"model": "test-model-b"}, {"promptVersion": "contracts/candidates/test"},
    {"codeRevision": "1" * 40}, {"workingTreeDirty": False}, {"startedAt": "2026-10-10T09:15:41.840Z"},
    {"elapsedMs": 2}, {"usageUnavailableReason": "test reason: the gateway withheld usage"},
    {"usage": USAGE, "usageUnavailableReason": None},
]


@pytest.mark.parametrize("changes", RUN_CHANGES, ids=lambda changes: next(iter(changes)))
def test_recording_digest_changes_with_any_run_field(changes):
    assert recording_digest(with_run(**changes)) != RECORDING_SHA


@pytest.mark.parametrize("changes", RUN_CHANGES, ids=lambda changes: next(iter(changes)))
def test_findings_digest_ignores_run_metadata(changes):
    assert findings_digest(with_run(**changes)) == FINDINGS_SHA


def _filename_changed(data):
    data["source"]["filename"] = "renamed.docx"


def _editable_flag_changed(data):
    data["source"]["clauses"][0]["editable"] = False


def _validation_changed(data):
    data["validation"] = {"status": "REJECTED", "errorCode": "TEST_OTHER_CODE"}


@pytest.mark.parametrize("change", [_filename_changed, _editable_flag_changed, _validation_changed],
                         ids=lambda value: value.__name__.strip("_"))
def test_recording_digest_covers_source_and_validation_while_the_findings_digest_does_not(change):
    data = recording()
    change(data)
    artifact = CandidateRun.model_validate(data)
    assert recording_digest(artifact) != RECORDING_SHA
    assert findings_digest(artifact) == FINDINGS_SHA


@pytest.mark.parametrize("field, value", [
    ("explanation", "test explanation in other words"), ("proposedAmendment", "test amendment"),
    ("quote", "The annual fee is EUR 120,000"), ("category", "COMMERCIAL_RISK"),
    ("playbookReference", "COM-RENEWAL"), ("insertionAnchorId", ANCHOR[12]),
])
def test_findings_digest_changes_with_any_finding_field(field, value):
    data = recording()
    data["findings"][0][field] = value
    artifact = CandidateRun.model_validate(data)
    assert findings_digest(artifact) != FINDINGS_SHA
    assert recording_digest(artifact) != RECORDING_SHA


def test_findings_digest_changes_when_a_repetition_is_dropped():
    data = recording()
    del data["findings"][1]
    assert findings_digest(CandidateRun.model_validate(data)) != FINDINGS_SHA


@pytest.mark.parametrize("outcome", ["FAILED", "REFUSED"])
def test_findings_digest_is_none_without_output(outcome):
    assert findings_digest(without_output(outcome)) is None


def test_findings_digest_of_an_empty_output_is_that_of_an_empty_list():
    assert findings_digest(completed([])) == EMPTY_LIST_SHA


def test_comparison_key_is_document_playbook_instructions_and_mode():
    assert comparison_key(run()) == (SOURCE_SHA, PLAYBOOK_SHA, INSTRUCTIONS_SHA, "REPLAY")


def test_replay_and_live_recordings_are_not_comparable():
    assert comparison_key(with_run(mode="LIVE")) == (SOURCE_SHA, PLAYBOOK_SHA, INSTRUCTIONS_SHA, "LIVE")
    assert comparison_key(with_run(mode="LIVE")) != comparison_key(run())


def test_recordings_under_changed_instructions_are_not_comparable():
    data = recording()
    data["instructions"] += " Test addition."
    data["instructionsSha256"] = text_sha(data["instructions"])
    key = comparison_key(CandidateRun.model_validate(data))
    assert key == (SOURCE_SHA, PLAYBOOK_SHA, data["instructionsSha256"], "REPLAY")
    assert key != comparison_key(run())


def test_recordings_under_another_playbook_are_not_comparable():
    data = recording()
    _bind_playbook(data, (CORPUS / "dora.json").read_text(encoding="utf-8"))
    assert comparison_key(CandidateRun.model_validate(data)) == (
        SOURCE_SHA, DORA_PLAYBOOK_SHA, INSTRUCTIONS_SHA, "REPLAY")


@pytest.mark.parametrize("changes", [
    {"model": "test-model-b"}, {"promptVersion": "contracts/candidates/test"}, {"codeRevision": "1" * 40},
    {"startedAt": "2026-10-11T08:00:00Z"}, {"usage": USAGE, "usageUnavailableReason": None},
], ids=lambda changes: next(iter(changes)))
def test_arms_that_differ_in_model_prompt_or_time_stay_comparable(changes):
    assert comparison_key(with_run(**changes)) == comparison_key(run())


# --- Usage in the score --------------------------------------------------------------


def test_score_carries_the_usage_block_when_the_recording_carries_usage():
    score = evaluate_candidates(with_run(usage=USAGE, usageUnavailableReason=None))
    assert score["usage"] == {
        "inputTokens": 5200, "outputTokens": 1800, "cacheReadTokens": 1200, "thinkingTokens": 600,
        "providerRequestId": "test-request-1",
    }
    assert score["run"]["usage"] == score["usage"]
    assert set(score["unavailable"]) == {"severityAccuracy", "wholeDocumentClauseCoverage", "amendmentQuality"}


def test_score_without_usage_has_no_usage_block_and_gives_the_recorded_reason():
    score = evaluate_candidates(with_run(usage=None, usageUnavailableReason="test reason: the gateway withheld usage"))
    assert "usage" not in score
    assert score["unavailable"]["tokenUsageAndCost"] == "test reason: the gateway withheld usage"
    assert set(score["unavailable"]) == {
        "severityAccuracy", "wholeDocumentClauseCoverage", "amendmentQuality", "tokenUsageAndCost"}


def test_usage_adds_one_block_to_the_score_and_changes_no_figure():
    plain = evaluate_candidates(run())
    with_usage = evaluate_candidates(with_run(usage=USAGE, usageUnavailableReason=None))
    assert list(with_usage) == list(plain) + ["usage"]
    assert figures(with_usage) == figures(plain)
    assert with_usage["findings"] == plain["findings"]


# --- Command line --------------------------------------------------------------------


def test_cli_writes_the_committed_score_byte_for_byte(tmp_path, monkeypatch):
    out = tmp_path / "score.json"
    cli(monkeypatch, REPLAY, "--document", BASE_DOCUMENT, "--out", out)
    assert out.read_bytes() == SCORE.read_bytes()


def test_cli_prints_the_same_score_when_no_file_is_named(monkeypatch, capsys):
    cli(monkeypatch, REPLAY, "--document", BASE_DOCUMENT)
    assert capsys.readouterr().out == SCORE.read_text(encoding="utf-8")


def test_cli_refuses_a_recording_of_another_document_and_writes_nothing(tmp_path, monkeypatch):
    out = tmp_path / "score.json"
    with pytest.raises(ValueError, match="document hash mismatch"):
        cli(monkeypatch, REPLAY, "--document", CORPUS / "ict-changed.docx", "--out", out)
    assert not out.exists()


def test_cli_scores_against_a_reference_file(tmp_path, monkeypatch):
    gold = tmp_path / "reference.json"
    gold.write_text(json.dumps(reference_data([expected("COM-FEES", 2), expected("COM-EXIT"), expected("COM-SLA", 4)])),
                    encoding="utf-8")
    out = tmp_path / "score.json"
    cli(monkeypatch, REPLAY, "--document", BASE_DOCUMENT, "--reference", gold, "--out", out)
    match = json.loads(out.read_text(encoding="utf-8"))["issueMatch"]
    assert strict(match) == {
        "truePositives": 2, "falsePositives": 2, "falseNegatives": 1, "precision": 0.5, "recall": 2 / 3,
    }
    assert match["referenceStatus"] == "DRAFT"
    assert match["independentReviewClaimVerified"] is False


def test_cli_refuses_a_reference_for_another_document(tmp_path, monkeypatch):
    gold = tmp_path / "reference.json"
    gold.write_text(json.dumps(reference_data([], sourceSha256=CHANGED_SHA)), encoding="utf-8")
    out = tmp_path / "score.json"
    with pytest.raises(ValueError, match="different source or playbook"):
        cli(monkeypatch, REPLAY, "--document", BASE_DOCUMENT, "--reference", gold, "--out", out)
    assert not out.exists()
