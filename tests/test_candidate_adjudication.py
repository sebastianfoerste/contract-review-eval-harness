"""Two annotations of one cell, written adjudication, hash-bound reference.

Every annotator, rationale and decision in this file is test text. None of it is an
annotation of the corpus or a legal view on it.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval.candidate_adjudication import (
    ADJUDICATION_SCHEMA, EVIDENCE_MARKERS, Adjudication, compare, main, prepare, render_ledger, resolve,
)
from contract_eval.candidate_annotation import Annotation, compile_reference, corpus_bindings, load_corpus
from contract_eval.candidates import CandidateReference, CandidateRun, digest, evaluate_candidates

CORPUS = Path(__file__).resolve().parents[1] / "candidates" / "mycounsel"
EVIDENCE = "test-note-2026-10-11"
REASONING = "Test reasoning for this decision, not legal validation."

FEES = ("COM-FEES", 2)
EXIT_MISSING = ("COM-EXIT", None)
EXIT_AT_11 = ("COM-EXIT", 11)
SLA = ("COM-SLA", 4)


def run() -> CandidateRun:
    return CandidateRun.model_validate_json((CORPUS / "replay-run.json").read_text())


def annotation(letter: str, places, **overrides) -> Annotation:
    corpus = load_corpus(CORPUS)
    base = {
        "schema": "mycounsel.candidate-annotation.v1", "variant": "base", "playbook": "commercial",
        "documentSha256": corpus.document("base").sha256, "playbookSha256": corpus.playbooks["commercial"],
        **corpus_bindings(CORPUS),
        "annotator": f"Test Annotator {letter}", "annotatedOn": "2026-10-11", "sawModelOutput": False,
        "issues": [
            {"playbookReference": entry, "paragraph": paragraph, "missingClause": paragraph is None,
             "rationale": f"Test wording of annotator {letter} on {entry}, not legal validation",
             "confidence": "HIGH" if letter == "A" else "MEDIUM"}
            for entry, paragraph in places
        ],
    }
    base.update(overrides)
    return Annotation.model_validate(base)


def first(**overrides) -> Annotation:
    return annotation("A", [FEES, EXIT_MISSING], **overrides)


def second(**overrides) -> Annotation:
    return annotation("B", [FEES, EXIT_AT_11, SLA], **overrides)


def sha(model) -> str:
    """Stands in for the hash of the file bytes, which the command line computes."""
    return digest(json.dumps(model.model_dump(by_alias=True), sort_keys=True))


DECISIONS = {EXIT_MISSING: "INCLUDE", EXIT_AT_11: "EXCLUDE", SLA: "EXCLUDE"}


def record(a: Annotation, b: Annotation, decisions=DECISIONS, **overrides) -> dict:
    """A prepared record with every entry decided and the signature fields filled."""
    raw = prepare(a, b, sha(a), sha(b))
    for entry in raw["decisions"]:
        entry["decision"] = decisions[(entry["playbookReference"], entry["paragraph"])]
        entry["reasoning"] = REASONING
    raw.update(adjudicator="Test Adjudicator", adjudicatedOn="2026-10-12",
               independentAnnotator="A", reviewerEvidence=EVIDENCE)
    raw.update(overrides)
    return raw


def resolved(a: Annotation, b: Annotation, raw: dict) -> dict:
    adjudication = Adjudication.model_validate(raw)
    return resolve(a, b, adjudication, CORPUS, sha(a), sha(b), sha(adjudication))


def keys(items) -> list[tuple[str, int | None]]:
    return [(item.playbookReference, item.paragraph) for item in items]


def test_identical_issue_sets_agree_completely():
    comparison = compare(first(), annotation("B", [EXIT_MISSING, FEES]))
    assert keys(comparison.agreed) == [EXIT_MISSING, FEES]
    assert comparison.onlyInA == comparison.onlyInB == comparison.disagreements == []
    stats = comparison.statistics
    assert (stats.agreed, stats.onlyInA, stats.onlyInB, stats.positiveAgreement) == (2, 0, 0, 1.0)


def test_one_sided_issues_are_location_or_presence_disagreements():
    comparison = compare(first(), second())
    assert keys(comparison.agreed) == [FEES]
    assert keys(comparison.onlyInA) == [EXIT_MISSING]
    assert keys(comparison.onlyInB) == [EXIT_AT_11, SLA]
    assert [(d.playbookReference, d.paragraph, d.raisedBy, d.kind) for d in comparison.disagreements] == [
        ("COM-EXIT", None, "A", "LOCATION"),
        ("COM-EXIT", 11, "B", "LOCATION"),
        ("COM-SLA", 4, "B", "PRESENCE"),
    ]
    stats = comparison.statistics
    assert (stats.agreed, stats.onlyInA, stats.onlyInB) == (1, 1, 2)
    assert stats.positiveAgreement == pytest.approx(2 * 1 / (2 + 3))
    assert "Descriptive statistics" in stats.label and "not a pass mark" in stats.label


def test_a_second_place_for_an_entry_both_raised_is_a_location_disagreement():
    comparison = compare(annotation("A", [FEES, ("COM-FEES", 3)]), annotation("B", [FEES]))
    assert [(d.paragraph, d.raisedBy, d.kind) for d in comparison.disagreements] == [(3, "A", "LOCATION")]


def test_positive_agreement_is_undefined_when_neither_annotator_raised_an_issue():
    comparison = compare(annotation("A", []), annotation("B", []))
    assert comparison.statistics.positiveAgreement is None
    assert "not defined" in render_ledger(comparison)


def test_no_kappa_is_computed():
    comparison = compare(first(), second())
    assert "kappa" not in json.dumps(comparison.model_dump(by_alias=True)).lower()
    assert "Kappa: not computed" in render_ledger(comparison)


@pytest.mark.parametrize("overrides, message", [
    ({"variant": "changed"}, "different cells"),
    ({"playbook": "dora"}, "different cells"),
    ({"documentSha256": "0" * 64}, "different documents"),
    ({"playbookSha256": "0" * 64}, "different playbooks"),
    ({"annotator": "  test annotator a "}, "same annotator"),
    ({"annotator": "Test   Annotator\u00a0A"}, "same annotator"),  # run of spaces, no-break space
    ({"annotator": "\uff34\uff45\uff53\uff54 Annotator A"}, "same annotator"),  # full-width letters
    ({"annotator": "Test\u200b Annotator A"}, "same annotator"),  # zero-width space
    ({"annotator": "   "}, "must name their annotator"),
    ({"annotator": "\u200b"}, "must name their annotator"),
])
def test_compare_refuses_another_cell_or_one_annotator(overrides, message):
    with pytest.raises(ValueError, match=message):
        compare(first(), second(**overrides))


def test_prepare_writes_a_blank_record_bound_to_both_annotation_files():
    a, b = first(), second()
    raw = prepare(a, b, sha(a), sha(b))
    assert raw["schema"] == ADJUDICATION_SCHEMA == "mycounsel.candidate-adjudication.v1"
    assert (raw["variant"], raw["playbook"]) == ("base", "commercial")
    assert (raw["documentSha256"], raw["playbookSha256"]) == (a.documentSha256, a.playbookSha256)
    assert (raw["annotationASha256"], raw["annotationBSha256"]) == (sha(a), sha(b))
    assert (raw["annotatorA"], raw["annotatorB"]) == ("Test Annotator A", "Test Annotator B")
    assert raw["decisions"] == [
        {"playbookReference": "COM-EXIT", "paragraph": None, "missingClause": True,
         "raisedBy": "A", "kind": "LOCATION", "decision": None, "reasoning": ""},
        {"playbookReference": "COM-EXIT", "paragraph": 11, "missingClause": False,
         "raisedBy": "B", "kind": "LOCATION", "decision": None, "reasoning": ""},
        {"playbookReference": "COM-SLA", "paragraph": 4, "missingClause": False,
         "raisedBy": "B", "kind": "PRESENCE", "decision": None, "reasoning": ""},
    ]
    assert (raw["adjudicator"], raw["adjudicatedOn"]) == ("", "")
    assert raw["independentAnnotator"] is None and raw["reviewerEvidence"] is None
    Adjudication.model_validate(raw)


def test_prepare_is_deterministic_and_independent_of_issue_order():
    a, b = first(), second()
    once = json.dumps(prepare(a, b, "a" * 64, "b" * 64))
    assert json.dumps(prepare(a, b, "a" * 64, "b" * 64)) == once
    shuffled = prepare(annotation("A", [EXIT_MISSING, FEES]), annotation("B", [SLA, EXIT_AT_11, FEES]),
                       "a" * 64, "b" * 64)
    assert json.dumps(shuffled) == once


def test_prepare_orders_decisions_by_entry_and_place_before_raiser():
    raw = prepare(annotation("A", [SLA, EXIT_AT_11]), annotation("B", [EXIT_MISSING, ("COM-FEES", 3)]),
                  "a" * 64, "b" * 64)
    assert [(d["playbookReference"], d["paragraph"], d["raisedBy"]) for d in raw["decisions"]] == [
        ("COM-EXIT", None, "B"), ("COM-EXIT", 11, "A"), ("COM-FEES", 3, "B"), ("COM-SLA", 4, "A"),
    ]


@pytest.mark.parametrize("overrides, message", [
    ({"sawModelOutput": True}, "annotation B does not attest"),
    ({"sawModelOutput": None}, "annotation B does not attest"),
    ({"annotatedOn": ""}, "annotation B has no annotation date"),
    # The annotation model checks the shape of the date only.
    ({"annotatedOn": "2026-02-30"}, "annotation B is dated '2026-02-30', which is not a calendar date"),
    ({"annotatedOn": "2026-10-11\n"}, "which is not a calendar date"),
])
def test_prepare_refuses_annotations_that_could_never_be_resolved(overrides, message):
    a, b = first(), second(**overrides)
    with pytest.raises(ValueError, match=message):
        prepare(a, b, sha(a), sha(b))




def test_resolved_reference_holds_agreed_and_included_issues_with_both_wordings():
    a, b = first(), second()
    raw = record(a, b)
    reference = resolved(a, b, raw)
    parsed = CandidateReference.model_validate(reference)
    assert parsed.status == "INDEPENDENTLY_REVIEWED"
    artifact = run()
    assert [(i.playbookReference, i.anchorId, i.missingClause) for i in parsed.issues] == [
        ("COM-EXIT", None, True),
        ("COM-FEES", artifact.findings[0].anchorId, False),
    ]
    included, agreed = parsed.issues
    assert agreed.rationale == (
        "Annotator A (confidence HIGH): Test wording of annotator A on COM-FEES, not legal validation\n"
        "Annotator B (confidence MEDIUM): Test wording of annotator B on COM-FEES, not legal validation"
    )
    assert included.rationale == (
        "Annotator A only (confidence HIGH): Test wording of annotator A on COM-EXIT, not legal validation\n"
        f"Adjudication, INCLUDE: {REASONING}"
    )


def test_resolved_reference_carries_the_evidence_reference_and_all_three_hashes():
    a, b = first(), second()
    raw = record(a, b, independentAnnotator="B")
    reference = resolved(a, b, raw)
    evidence = reference["reviewerEvidence"]
    assert evidence == (
        f"{EVIDENCE}; independent-annotator:B; adjudication-sha256:{sha(Adjudication.model_validate(raw))}; "
        f"annotation-a-sha256:{sha(a)}; annotation-b-sha256:{sha(b)}"
    )
    assert [evidence.count(marker) for marker in EVIDENCE_MARKERS] == [1, 1, 1, 1]
    # Names stay in the annotations and the record. The reference is the public file.
    assert "Test Annotator" not in json.dumps(reference) and "Test Adjudicator" not in json.dumps(reference)


def test_an_included_issue_of_annotator_b_keeps_b_wording_and_the_recorder_anchor():
    a, b = first(), second()
    reference = resolved(a, b, record(a, b, {EXIT_MISSING: "EXCLUDE", EXIT_AT_11: "INCLUDE", SLA: "EXCLUDE"}))
    included = next(issue for issue in reference["issues"] if issue["playbookReference"] == "COM-EXIT")
    assert included["anchorId"] == run().source.clauses[11].id and included["missingClause"] is False
    assert included["rationale"] == (
        "Annotator B only (confidence MEDIUM): Test wording of annotator B on COM-EXIT, not legal validation\n"
        f"Adjudication, INCLUDE: {REASONING}"
    )


@pytest.mark.parametrize("decisions, expected", [
    ({EXIT_MISSING: "INCLUDE", EXIT_AT_11: "EXCLUDE", SLA: "EXCLUDE"}, (2, 2, 0)),
    ({EXIT_MISSING: "INCLUDE", EXIT_AT_11: "EXCLUDE", SLA: "INCLUDE"}, (2, 2, 1)),
    ({EXIT_MISSING: "EXCLUDE", EXIT_AT_11: "INCLUDE", SLA: "EXCLUDE"}, (1, 3, 1)),
    ({EXIT_MISSING: "EXCLUDE", EXIT_AT_11: "EXCLUDE", SLA: "EXCLUDE"}, (1, 3, 0)),
])
def test_resolved_reference_scores_the_committed_replay(decisions, expected):
    a, b = first(), second()
    reference = CandidateReference.model_validate(resolved(a, b, record(a, b, decisions)))
    match = evaluate_candidates(run(), reference)["issueMatch"]
    assert (match["truePositives"], match["falsePositives"], match["falseNegatives"]) == expected
    assert match["referenceStatus"] == "INDEPENDENTLY_REVIEWED"
    assert match["referenceEvidence"].startswith(EVIDENCE)
    # The evaluator reports the claim; it does not verify the reviewer.
    assert match["independentReviewClaimVerified"] is False


def test_full_agreement_resolves_to_the_same_issue_keys_as_the_single_annotation_compiler():
    a, b = first(), annotation("B", [EXIT_MISSING, FEES])
    adjudicated = resolved(a, b, record(a, b))
    compiled = compile_reference(a, CORPUS, annotation_sha256="0" * 64)
    as_keys = lambda ref: sorted((i["playbookReference"], i["anchorId"] or "", i["missingClause"])  # noqa: E731
                                 for i in ref["issues"])
    assert as_keys(adjudicated) == as_keys(compiled)
    assert (adjudicated["sourceSha256"], adjudicated["playbookSha256"]) == (
        compiled["sourceSha256"], compiled["playbookSha256"])


def test_zero_disagreements_still_need_a_signed_record():
    a, b = first(), annotation("B", [FEES, EXIT_MISSING])
    blank = prepare(a, b, sha(a), sha(b))
    assert blank["decisions"] == []
    with pytest.raises(ValueError, match="names no adjudicator"):
        resolved(a, b, blank)
    reference = resolved(a, b, record(a, b))
    assert reference["status"] == "INDEPENDENTLY_REVIEWED" and len(reference["issues"]) == 2


@pytest.mark.parametrize("overrides", [
    {"variant": "changed"}, {"playbook": "dora"}, {"documentSha256": "0" * 64}, {"playbookSha256": "0" * 64},
])
def test_resolve_refuses_a_record_for_a_different_cell(overrides):
    a, b = first(), second()
    with pytest.raises(ValueError, match="bound to a different cell"):
        resolved(a, b, record(a, b, **overrides))


def test_resolve_refuses_two_annotations_by_the_same_annotator():
    a, b = first(), second()
    raw = record(a, b)
    same = second(annotator="TEST ANNOTATOR A")
    with pytest.raises(ValueError, match="same annotator"):
        resolve(a, same, Adjudication.model_validate(raw), CORPUS, sha(a), sha(b), "c" * 64)


@pytest.mark.parametrize("side", ["A", "B"])
def test_resolve_refuses_a_stale_record_after_an_annotation_changed(side):
    a, b = first(), second()
    raw = record(a, b)
    note = "Test edit made after the record was prepared"
    edited_a, edited_b = (first(uncertainties=note), b) if side == "A" else (a, second(uncertainties=note))
    assert compare(edited_a, edited_b).disagreements == compare(a, b).disagreements
    with pytest.raises(ValueError, match="an annotation changed after the record was prepared"):
        resolved(edited_a, edited_b, raw)


def test_resolve_refuses_annotations_passed_in_the_opposite_order():
    a, b = first(), second()
    with pytest.raises(ValueError, match="opposite order"):
        resolved(b, a, record(a, b))


def test_resolve_refuses_a_record_that_renames_an_annotator():
    a, b = first(), second()
    with pytest.raises(ValueError, match="names different annotators"):
        resolved(a, b, record(a, b, annotatorB="Test Annotator C"))


def test_resolve_refuses_a_missing_decision():
    a, b = first(), second()
    raw = record(a, b)
    del raw["decisions"][2]
    with pytest.raises(ValueError, match=r"no decision for: COM-SLA \(P4\)"):
        resolved(a, b, raw)


@pytest.mark.parametrize("extra", [
    {"playbookReference": "COM-FEES", "paragraph": 2, "missingClause": False},  # agreed, not a disagreement
    {"playbookReference": "COM-RENEWAL", "paragraph": 3, "missingClause": False},  # raised by neither
])
def test_resolve_refuses_an_extra_decision(extra):
    a, b = first(), second()
    raw = record(a, b)
    raw["decisions"].append({**extra, "raisedBy": "A", "kind": "PRESENCE",
                             "decision": "INCLUDE", "reasoning": REASONING})
    with pytest.raises(ValueError, match="not a current disagreement"):
        resolved(a, b, raw)


@pytest.mark.parametrize("field, value", [("raisedBy", "A"), ("kind", "LOCATION")])
def test_resolve_refuses_a_decision_that_misstates_raiser_or_kind(field, value):
    a, b = first(), second()
    raw = record(a, b)
    assert raw["decisions"][2][field] != value
    raw["decisions"][2][field] = value
    with pytest.raises(ValueError, match="misstates who raised it or its kind"):
        resolved(a, b, raw)


def test_resolve_refuses_an_undecided_disagreement():
    a, b = first(), second()
    raw = record(a, b)
    raw["decisions"][1].update(decision=None, reasoning="")
    with pytest.raises(ValueError, match=r"undecided disagreement: COM-EXIT \(P11\)"):
        resolved(a, b, raw)


@pytest.mark.parametrize("reasoning", [
    "", "   \n ", "ok", "Agreed.", "see above", "........................", "yes I agree", "I do agree with it",
])
def test_a_decision_without_written_reasoning_is_rejected(reasoning):
    a, b = first(), second()
    raw = record(a, b)
    raw["decisions"][0]["reasoning"] = reasoning
    with pytest.raises(ValidationError, match="written reasoning"):
        resolved(a, b, raw)


@pytest.mark.parametrize("overrides, message", [
    ({"adjudicator": "  "}, "names no adjudicator"),
    ({"adjudicatedOn": ""}, "has no date"),
    ({"independentAnnotator": None}, "which annotator is independent"),
    ({"reviewerEvidence": None}, "no reference to the note"),
    ({"reviewerEvidence": "   "}, "no reference to the note"),
])
def test_resolve_refuses_missing_signature_or_independence_fields(overrides, message):
    a, b = first(), second()
    with pytest.raises(ValueError, match=message):
        resolved(a, b, record(a, b, **overrides))


@pytest.mark.parametrize("overrides, message", [
    ({"sawModelOutput": True}, "annotation B does not attest"),
    ({"sawModelOutput": None}, "annotation B does not attest"),
    ({"annotatedOn": ""}, "annotation B has no annotation date"),
    ({"annotatedOn": "2026-02-30"}, "which is not a calendar date"),
])
def test_resolve_refuses_an_annotator_who_saw_model_output_or_gave_no_date(overrides, message):
    a, b = first(), second()
    adjudication = Adjudication.model_validate(record(a, b))
    with pytest.raises(ValueError, match=message):
        resolve(a, second(**overrides), adjudication, CORPUS, sha(a), sha(b), "c" * 64)


@pytest.mark.parametrize("dates", [("2026-10-11", "2026-10-11"), ("2026-10-09", "2026-10-11"),
                                   ("2026-10-11", "2026-10-09")])
def test_resolve_refuses_an_adjudication_dated_before_an_annotation(dates):
    a, b = first(annotatedOn=dates[0]), second(annotatedOn=dates[1])
    with pytest.raises(ValueError, match="dated before an annotation"):
        resolved(a, b, record(a, b, adjudicatedOn="2026-10-10"))
    assert resolved(a, b, record(a, b, adjudicatedOn="2026-10-11"))["status"] == "INDEPENDENTLY_REVIEWED"




@pytest.mark.parametrize("place, message", [
    (("COM-NOPE", 4), "unknown playbook entry COM-NOPE"),
    (("COM-SLA", 99), "paragraph 99 is outside the document"),
])
def test_resolve_refuses_an_unresolvable_issue_even_when_it_is_excluded(place, message):
    a, b = first(), annotation("B", [FEES, place])
    decisions = {EXIT_MISSING: "INCLUDE", place: "EXCLUDE"}
    with pytest.raises(ValueError, match=message):
        resolved(a, b, record(a, b, decisions))


@pytest.mark.parametrize("mutate, message", [
    (lambda raw: raw.update(adjudicatedOn="12.10.2026"), "ISO date"),
    (lambda raw: raw.update(adjudicatedOn="2026-02-30"), "ISO date"),
    (lambda raw: raw.update(adjudicatedOn="20261012"), "ISO date"),
    (lambda raw: raw.update(adjudicatedOn="2026-W41-1"), "ISO date"),
    (lambda raw: raw.update(adjudicatedOn="2026-10-12\n"), "ISO date"),
    (lambda raw: raw.update(independentAnnotator="C"), "independentAnnotator"),
    (lambda raw: raw.update(reviewerEvidence="line one\nline two"), "single line"),
    (lambda raw: raw.update(reviewerEvidence="line one\u2028line two"), "single line"),
    (lambda raw: raw.update(reviewerEvidence="note\twith a tab"), "single line"),
    (lambda raw: raw.update(reviewerEvidence="note; adjudication-sha256:" + "0" * 64),
     "label the reference adds itself"),
    (lambda raw: raw.update(reviewerEvidence="note; Annotation-A-SHA256:" + "0" * 64),
     "label the reference adds itself"),
    (lambda raw: raw.update(note="not part of the schema"), "Extra inputs are not permitted"),
    (lambda raw: raw["decisions"][0].update(note="not part of the schema"), "Extra inputs are not permitted"),
    (lambda raw: raw["decisions"][0].update(decision="MAYBE"), "INCLUDE"),
    (lambda raw: raw["decisions"][0].update(paragraph=3), "missing clause has no paragraph"),
    (lambda raw: raw["decisions"].append(dict(raw["decisions"][0])), "duplicate decision"),
    (lambda raw: raw.update(annotationASha256="not-a-hash"), "annotationASha256"),
])
def test_record_model_rejects_malformed_records(mutate, message):
    raw = record(first(), second())
    mutate(raw)
    with pytest.raises(ValidationError, match=message):
        Adjudication.model_validate(raw)


def test_hashes_must_be_sha256_digests():
    a, b = first(), second()
    with pytest.raises(ValueError, match="a_sha256 is not a SHA-256"):
        prepare(a, b, "abc", sha(b))
    adjudication = Adjudication.model_validate(record(a, b))
    with pytest.raises(ValueError, match="adjudication_sha256 is not a SHA-256"):
        resolve(a, b, adjudication, CORPUS, sha(a), sha(b), "abc")
    with pytest.raises(ValueError, match="adjudication_sha256 is not a SHA-256"):
        resolve(a, b, adjudication, CORPUS, sha(a), sha(b), "c" * 64 + "\n")
    with pytest.raises(ValueError, match="are identical"):
        prepare(a, b, sha(a), sha(a))
    with pytest.raises(ValueError, match="are identical"):
        resolve(a, b, adjudication, CORPUS, sha(a), sha(b), sha(b))


def test_resolve_revalidates_models_changed_after_they_were_parsed():
    a, b = first(), second()
    adjudication = Adjudication.model_validate(record(a, b))
    adjudication.decisions[0].reasoning = ""
    with pytest.raises(ValidationError, match="written reasoning"):
        resolve(a, b, adjudication, CORPUS, sha(a), sha(b), "c" * 64)
    changed = first()
    changed.issues.append(changed.issues[0])
    with pytest.raises(ValidationError, match="duplicate expected issue"):
        resolve(changed, b, Adjudication.model_validate(record(a, b)), CORPUS, sha(a), sha(b), "c" * 64)


def test_ledger_names_every_disagreement_and_labels_the_statistics_descriptive():
    ledger = render_ledger(compare(first(), second(uncertainties="Test note on entry framing")))
    assert "# Disagreement ledger: base / commercial" in ledger
    assert "| 1 | COM-EXIT | missing clause | A | LOCATION | B raised it at: P11 |" in ledger
    assert "| 2 | COM-EXIT | P11 | B | LOCATION | A raised it at: missing clause |" in ledger
    assert "| 3 | COM-SLA | P4 | B | PRESENCE | A did not raise this entry |" in ledger
    assert "   > Test wording of annotator B on COM-SLA, not legal validation" in ledger
    assert "Descriptive statistics" in ledger and "not a pass mark" in ledger
    assert "- Agreed issues: 1" in ledger and "- Only annotator A: 1" in ledger and "- Only annotator B: 2" in ledger
    assert "Positive agreement, 2 x agreed / (|A| + |B|): 0.400" in ledger
    assert "Unresolved disagreements: 3" in ledger
    assert "Written adjudication is required before a reference can be frozen." in ledger
    assert "Annotator A: none recorded." in ledger and "> Test note on entry framing" in ledger


def test_ledger_without_disagreements_still_requires_a_signed_record():
    ledger = render_ledger(compare(first(), annotation("B", [FEES, EXIT_MISSING])))
    assert "Unresolved disagreements: 0" in ledger
    assert "Written adjudication is required before a reference can be frozen." in ledger
    assert "empty decision list is still required" in ledger


def _write(path: Path, model) -> Path:
    path.write_text(json.dumps(model.model_dump(by_alias=True), indent=2) + "\n", encoding="utf-8")
    return path


def test_cli_compare_prepare_resolve_with_hashes_from_file_bytes(tmp_path, capsys):
    file_a = _write(tmp_path / "a.annotation.json", first())
    file_b = _write(tmp_path / "b.annotation.json", second())

    main(["compare", str(file_a), str(file_b)])
    assert "Unresolved disagreements: 3" in capsys.readouterr().out
    ledger = tmp_path / "ledger.md"
    main(["compare", str(file_a), str(file_b), "--markdown", str(ledger)])
    assert "| 3 | COM-SLA | P4 | B | PRESENCE |" in ledger.read_text(encoding="utf-8")

    file_record = tmp_path / "base-commercial.adjudication.json"
    main(["prepare", str(file_a), str(file_b), "--out", str(file_record)])
    raw = json.loads(file_record.read_text(encoding="utf-8"))
    assert raw["annotationASha256"] == digest(file_a.read_bytes())
    assert raw["annotationBSha256"] == digest(file_b.read_bytes())
    with pytest.raises(ValueError, match="undecided disagreement"):
        main(["resolve", str(file_a), str(file_b), str(file_record), "--corpus", str(CORPUS)])

    for entry in raw["decisions"]:
        entry.update(decision=DECISIONS[(entry["playbookReference"], entry["paragraph"])], reasoning=REASONING)
    raw.update(adjudicator="Test Adjudicator", adjudicatedOn="2026-10-12",
               independentAnnotator="A", reviewerEvidence=EVIDENCE)
    file_record.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    out = tmp_path / "reference.json"
    main(["resolve", str(file_a), str(file_b), str(file_record), "--corpus", str(CORPUS), "--out", str(out)])
    reference = CandidateReference.model_validate_json(out.read_text(encoding="utf-8"))
    assert reference.status == "INDEPENDENTLY_REVIEWED"
    for path in (file_a, file_b, file_record):
        assert digest(path.read_bytes()) in reference.reviewerEvidence
    match = evaluate_candidates(run(), reference)["issueMatch"]
    assert (match["truePositives"], match["falsePositives"], match["falseNegatives"]) == (2, 2, 0)

    # An annotation edited after signing no longer matches the record.
    _write(file_b, second(uncertainties="Test edit made after signing"))
    with pytest.raises(ValueError, match="an annotation changed after the record was prepared"):
        main(["resolve", str(file_a), str(file_b), str(file_record), "--corpus", str(CORPUS)])


def test_cli_prepare_refuses_to_overwrite_an_existing_record(tmp_path):
    file_a = _write(tmp_path / "a.annotation.json", first())
    file_b = _write(tmp_path / "b.annotation.json", second())
    file_record = tmp_path / "record.json"
    main(["prepare", str(file_a), str(file_b), "--out", str(file_record)])
    file_record.write_text("written decisions live here", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        main(["prepare", str(file_a), str(file_b), "--out", str(file_record)])
    assert file_record.read_text(encoding="utf-8") == "written decisions live here"


def test_cli_outputs_never_replace_an_annotation_or_a_record(tmp_path):
    file_a = _write(tmp_path / "a.annotation.json", first())
    file_b = _write(tmp_path / "b.annotation.json", second())
    file_record = tmp_path / "record.json"
    main(["prepare", str(file_a), str(file_b), "--out", str(file_record)])
    raw = json.loads(file_record.read_text(encoding="utf-8"))
    for entry in raw["decisions"]:
        entry.update(decision=DECISIONS[(entry["playbookReference"], entry["paragraph"])], reasoning=REASONING)
    raw.update(adjudicator="Test Adjudicator", adjudicatedOn="2026-10-12",
               independentAnnotator="A", reviewerEvidence=EVIDENCE)
    file_record.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    # A record someone is still editing, with a stray comma, is a record all the same.
    unfinished = tmp_path / "unfinished.json"
    unfinished.write_text(file_record.read_text(encoding="utf-8").replace("[", "[,", 1), encoding="utf-8")
    compare_to = ["compare", str(file_a), str(file_b), "--markdown"]
    resolve_to = ["resolve", str(file_a), str(file_b), str(file_record), "--corpus", str(CORPUS), "--out"]

    written = {path: path.read_bytes() for path in (file_a, file_b, file_record, unfinished)}
    for target in written:
        for command in (compare_to, resolve_to):
            with pytest.raises(FileExistsError, match="refusing to overwrite"):
                main([*command, str(target)])
    assert {path: path.read_bytes() for path in written} == written

    # A ledger and a reference are derived from those files; a second run replaces them.
    ledger, reference = tmp_path / "ledger.md", tmp_path / "reference.json"
    for _ in range(2):
        main([*compare_to, str(ledger)])
        main([*resolve_to, str(reference)])
    assert "Unresolved disagreements: 3" in ledger.read_text(encoding="utf-8")
    parsed = CandidateReference.model_validate_json(reference.read_text(encoding="utf-8"))
    assert parsed.status == "INDEPENDENTLY_REVIEWED"
