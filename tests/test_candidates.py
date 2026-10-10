from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval.candidates import (
    CandidateRun, CandidateReference, comparison_key, digest,
    evaluate_candidates, recording_digest, verify_document,
)

CORPUS = Path(__file__).resolve().parents[1] / "candidates" / "mycounsel"


def run():
    return CandidateRun.model_validate_json((CORPUS / "replay-run.json").read_text())


def reference(artifact):
    first, *_, missing = artifact.findings
    return CandidateReference.model_validate({
        "schema": "mycounsel.candidate-reference.v1",
        "sourceSha256": artifact.source.sha256,
        "playbookSha256": artifact.playbook.sha256,
        "status": "DRAFT", "reviewerEvidence": None,
        "issues": [
            {"playbookReference": f.playbookReference, "anchorId": f.anchorId,
             "missingClause": f.missingClause, "rationale": "Test expectation, not legal validation"}
            for f in (first, missing)
        ],
    })


def test_native_shape_does_not_invent_severity_or_clause_inventory():
    result = evaluate_candidates(run())
    assert result["attemptMode"] == "REPLAY"
    assert result["findingCount"] == 4
    assert result["duplicateCount"] == 1
    assert result["playbookReferenceValid"] == 3
    assert result["quotationValid"] == result["quotationDenominator"] == 3
    assert result["missingClauseValid"] == result["missingClauseDenominator"] == 1
    assert result["issueMatch"] is None
    assert set(result["unavailable"]) == {"severityAccuracy", "wholeDocumentClauseCoverage", "amendmentQuality", "tokenUsageAndCost"}


def test_duplicates_and_unknown_rules_cannot_inflate_precision():
    artifact = run()
    result = evaluate_candidates(artifact, reference(artifact))["issueMatch"]
    assert result["truePositives"] == 2
    assert result["falsePositives"] == 2
    assert result["falseNegatives"] == 0
    assert result["precision"] == 0.5
    assert result["recall"] == 1
    assert result["referenceStatus"] == "DRAFT"
    assert result["independentReviewClaimVerified"] is False


def test_document_and_anchor_binding_reject_tampering():
    artifact = run()
    verify_document(artifact, (CORPUS / "ict-base.docx").read_bytes())
    with pytest.raises(ValueError, match="document hash"):
        verify_document(artifact, (CORPUS / "ict-changed.docx").read_bytes())
    data = artifact.model_dump(by_alias=True)
    data["source"]["clauses"][0]["text"] = "invented"
    with pytest.raises(ValidationError, match="anchor mismatch"):
        CandidateRun.model_validate(data)
    data["source"]["clauses"][0]["id"] = digest(f'{artifact.source.sha256}:0:invented')
    with pytest.raises(ValueError, match="differ from original"):
        verify_document(CandidateRun.model_validate(data), (CORPUS / "ict-base.docx").read_bytes())


@pytest.mark.parametrize("field", ["playbook", "instructions"])
def test_changed_review_inputs_fail_closed(field):
    data = run().model_dump(by_alias=True)
    if field == "playbook":
        data[field]["instructions"] += " "
    else:
        data[field] += " "
    with pytest.raises(ValidationError, match="hash mismatch"):
        CandidateRun.model_validate(data)


def test_invalid_quotes_and_category_are_recomputed_even_if_recorder_claimed_acceptance():
    artifact = run()
    artifact.validation.status = "ACCEPTED"
    artifact.findings[0].quote = "fabricated"
    artifact.findings[1].category = "STATUTORY_REQUIREMENT"
    result = evaluate_candidates(artifact)
    assert result["findings"][0]["quotationValid"] is False
    assert result["findings"][1]["playbookReferenceValid"] is False


def test_missing_clause_cannot_pretend_to_have_a_quote_or_unknown_insertion_anchor():
    artifact = run()
    artifact.findings[-1].quote = "invented absence quotation"
    assert evaluate_candidates(artifact)["missingClauseValid"] == 0
    artifact.findings[-1].quote = ""
    artifact.findings[-1].insertionAnchorId = "0" * 64
    assert evaluate_candidates(artifact)["missingClauseValid"] == 0


def test_failed_attempt_remains_in_denominator_with_no_invented_zero_quality():
    data = run().model_dump(by_alias=True)
    data["run"]["outcome"] = "FAILED"
    data["findings"] = None
    data["validation"] = {"status": "NO_OUTPUT", "errorCode": "GATEWAY_FAILURE"}
    result = evaluate_candidates(CandidateRun.model_validate(data))
    assert result["attemptOutcome"] == "FAILED"
    assert result["findingCount"] == 0
    assert result["issueMatch"] is None


def test_incompatible_reference_and_false_independent_claim_fail():
    artifact = run()
    gold = reference(artifact)
    gold.sourceSha256 = "0" * 64
    with pytest.raises(ValueError, match="different source"):
        evaluate_candidates(artifact, gold)
    data = reference(artifact).model_dump(by_alias=True)
    data["status"] = "INDEPENDENTLY_REVIEWED"
    with pytest.raises(ValidationError, match="evidence reference"):
        CandidateReference.model_validate(data)


def test_replay_and_live_or_changed_instructions_are_not_comparable():
    artifact = run()
    other = deepcopy(artifact)
    assert comparison_key(artifact) == comparison_key(other)
    other.run.mode = "LIVE"
    assert comparison_key(artifact) != comparison_key(other)


def test_score_binds_to_exact_attempt_and_source_revision():
    artifact = run()
    result = evaluate_candidates(artifact)
    assert result["run"]["codeRevision"] == artifact.run.codeRevision
    assert result["run"]["workingTreeDirty"] is True
    assert result["instructionsSha256"] == artifact.instructionsSha256
    other = deepcopy(artifact)
    other.run.model = "another-model"
    assert recording_digest(other) != result["recordingSha256"]
    other.run.mode = "REPLAY"
    other.instructionsSha256 = "0" * 64
    assert comparison_key(artifact) != comparison_key(other)


def test_committed_report_reproduces_from_native_recording():
    import json
    expected = json.loads((CORPUS / "replay-score.json").read_text())
    assert evaluate_candidates(run()) == expected


def test_corpus_manifest_pins_every_variant_and_playbook():
    import json
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    assert manifest["corpusKind"] == "SYNTHETIC"
    assert manifest["referenceStatus"] == "DRAFT_NOT_INDEPENDENTLY_REVIEWED"
    assert {d["variant"] for d in manifest["documents"]} == {"base", "changed", "injection"}
    for document in manifest["documents"]:
        assert digest((CORPUS / document["filename"]).read_bytes()) == document["sha256"]
    for name, expected in manifest["playbooks"].items():
        assert digest((CORPUS / f"{name}.json").read_bytes()) == expected
