"""Blind pack, paragraph-numbered annotation, hash-bound DRAFT reference.

Every annotator, rationale and note in this file is test text. None of it is an
annotation of the corpus or a legal view on it. A test that changes the corpus or a pack
works on a copy under tmp_path; the committed corpus and pack are only read.
"""

import functools
import hashlib
import json
import re
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from contract_eval.candidate_annotation import (
    Annotation, build_pack, bundle_pack, compile_reference, corpus_bindings, load_corpus, load_source_register,
    main, require_filled, resolve_anchors, snapshot_text, verify_pack,
)
from contract_eval.candidates import CandidateReference, CandidateRun, document_paragraphs, evaluate_candidates

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "candidates" / "mycounsel"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
DOCUMENTS = {document["variant"]: document["sha256"] for document in MANIFEST["documents"]}
PLAYBOOKS = MANIFEST["playbooks"]
SNAPSHOT = "sources/eu-2022-2554-art30-oj-en.txt"
RATIONALE = "test rationale, not legal validation"

# The guideline tells the annotator that the first eight fields of a template are filled in.
TEMPLATE_FIELDS = [
    "schema", "variant", "playbook", "documentSha256", "playbookSha256", "corpusManifestSha256",
    "guidelineSha256", "sourceRegisterSha256", "annotator", "annotatedOn", "sawModelOutput", "issues",
    "uncertainties",
]
BINDING_HASHES = TEMPLATE_FIELDS[3:8]
ISSUE_FIELDS = {"playbookReference", "paragraph", "missingClause", "rationale", "confidence"}
PACK_FILES = [
    "GUIDELINE.md",
    "documents/base.paragraphs.md", "documents/changed.paragraphs.md", "documents/injection.paragraphs.md",
    "documents/ict-base.docx", "documents/ict-changed.docx", "documents/ict-injection.docx",
    "instructions.md",
    "playbooks/commercial.json", "playbooks/commercial.md", "playbooks/dora.json", "playbooks/dora.md",
    "sources/eu-2022-2554-art30-oj-en.txt", "sources/sources.json",
    "templates/base-commercial.annotation.json", "templates/base-dora.annotation.json",
    "templates/changed-commercial.annotation.json", "templates/changed-dora.annotation.json",
    "templates/injection-commercial.annotation.json", "templates/injection-dora.annotation.json",
]
# Worked out with shasum from "<document hash>:<paragraph number>:<paragraph text>".
CHANGED_P2 = "a9047a28369cc597500efd5fd9cd9e49193c727dfcd119f35ccedac599cbee0e"
INJECTION_P13 = "589969ee81f79bd59e9b2d274cec1b7f243f09927601d822ee9c4fd2b2b8caaf"
# README and guideline both end on this sentence. It says nothing about the documents.
SHARED_ON_PURPOSE = "The reference carries hashes and the letters A and B, not names."
STALE = "the pack is not what the corpus builds today"


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, raw: dict) -> Path:
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def edit_json(path: Path, change) -> None:
    raw = read_json(path)
    change(raw)
    write(path, raw)


def run() -> CandidateRun:
    return CandidateRun.model_validate_json((CORPUS / "replay-run.json").read_text(encoding="utf-8"))


def file_hashes(corpus_dir: Path = CORPUS) -> dict[str, str | None]:
    """The three pack bindings, taken from the file bytes without the code under test."""
    register = corpus_dir / "sources.json"
    return {
        "corpusManifestSha256": sha((corpus_dir / "manifest.json").read_bytes()),
        "guidelineSha256": sha((corpus_dir / "annotation" / "GUIDELINE.md").read_bytes()),
        "sourceRegisterSha256": sha(register.read_bytes()) if register.exists() else None,
    }


def issue(entry: str, paragraph: int | None, confidence: str = "HIGH", rationale: str = RATIONALE) -> dict:
    return {"playbookReference": entry, "paragraph": paragraph, "missingClause": paragraph is None,
            "rationale": rationale, "confidence": confidence}


FEES = issue("COM-FEES", 2)
EXIT_MISSING = issue("COM-EXIT", None, "MEDIUM")


def filled(corpus_dir: Path = CORPUS, cell: tuple[str, str] = ("base", "commercial"), **overrides) -> dict:
    """A filled annotation as it would lie in a file, bound to the corpus as its files stand."""
    manifest = read_json(corpus_dir / "manifest.json")
    variant, playbook = cell
    raw = {
        "schema": "mycounsel.candidate-annotation.v1", "variant": variant, "playbook": playbook,
        "documentSha256": {d["variant"]: d["sha256"] for d in manifest["documents"]}[variant],
        "playbookSha256": manifest["playbooks"][playbook],
        **file_hashes(corpus_dir),
        "annotator": "Test Annotator A", "annotatedOn": "2026-10-11", "sawModelOutput": False,
        "issues": [FEES, EXIT_MISSING], "uncertainties": "",
    }
    raw.update(overrides)
    return raw


def annotation(**overrides) -> Annotation:
    return Annotation.model_validate(filled(**overrides))


def compiled(**overrides) -> dict:
    return compile_reference(annotation(**overrides), CORPUS, annotation_sha256="a" * 64)


@pytest.fixture
def pack(tmp_path):
    out = tmp_path / "pack"
    return out, build_pack(CORPUS, out)


@pytest.fixture
def corpus_copy(tmp_path):
    """A private copy of the corpus that a test may change."""
    copy = tmp_path / "corpus"
    shutil.copytree(CORPUS, copy, ignore=shutil.ignore_patterns(
        "annotation-pack", "annotation-bundle", "experiments", "__pycache__"))
    return copy


def files_in(folder: Path) -> list[str]:
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())


def repin(copy: Path, playbook: str) -> None:
    edit_json(copy / "manifest.json",
              lambda manifest: manifest["playbooks"].update({playbook: sha((copy / f"{playbook}.json").read_bytes())}))


def add_entry(copy: Path, playbook: str, entry_id: str, category: str) -> None:
    edit_json(copy / f"{playbook}.json", lambda book: book["entries"].append(
        {"id": entry_id, "category": category, "requirement": "Test requirement, not a legal rule."}))
    repin(copy, playbook)


def change_instructions(copy: Path) -> None:
    edit_json(copy / "manifest.json",
              lambda manifest: manifest.update(instructions=manifest["instructions"] + " Test addition."))


def change_guideline(copy: Path) -> None:
    path = copy / "annotation" / "GUIDELINE.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nTest addition to the guideline.\n", encoding="utf-8")


def change_playbook(copy: Path) -> None:
    edit_json(copy / "commercial.json",
              lambda book: book["entries"][0].update(requirement="Test requirement, changed after the pack."))
    repin(copy, "commercial")


def edit_source(copy: Path, change) -> None:
    edit_json(copy / "sources.json", lambda register: change(register["sources"][0]))


def change_register(copy: Path) -> None:
    edit_source(copy, lambda source: source.update(currentTextNote="Test note, changed after the pack."))


def remove_register(copy: Path) -> None:
    (copy / "sources.json").unlink()


def change_snapshot_header(copy: Path) -> None:
    path = copy / SNAPSHOT
    text = path.read_text(encoding="utf-8")
    assert text.count("Fetched: 2026-10-11T18:13:00Z\n") == 1
    path.write_text(text.replace("Fetched: 2026-10-11T18:13:00Z\n", "Fetched: test edit of the header\n"),
                    encoding="utf-8")


def cite(source: dict, entry: str) -> None:
    source["usedBy"].append(entry)
    source["pinpoints"][entry] = "Article 30(9), test pinpoint"


def uncite(source: dict, entry: str) -> None:
    source["usedBy"].remove(entry)
    del source["pinpoints"][entry]


def prefill(out: Path) -> None:
    """Write a note into one template and bring its manifest line up to date."""
    relative = "templates/base-commercial.annotation.json"
    edit_json(out / relative, lambda template: template.update(uncertainties="Test hint, not an annotation."))
    edit_json(out / "MANIFEST.json",
              lambda manifest: manifest["files"].update({relative: sha((out / relative).read_bytes())}))


def test_corpus_bindings_are_the_hashes_of_manifest_guideline_and_register():
    assert corpus_bindings(CORPUS) == file_hashes(CORPUS)
    assert all(re.fullmatch(r"[a-f0-9]{64}", value) for value in corpus_bindings(CORPUS).values())


@pytest.mark.parametrize("shape", [{"paragraph": 2, "missingClause": True}, {"paragraph": None, "missingClause": False}])
def test_a_missing_clause_has_no_paragraph_and_a_located_issue_names_one(shape):
    with pytest.raises(ValidationError, match="a missing clause has no paragraph"):
        annotation(issues=[{**FEES, **shape}])


@pytest.mark.parametrize("rationale, message", [("", "at least 1 character"), ("  \n\t", "needs a written rationale")])
def test_a_blank_rationale_is_refused(rationale, message):
    with pytest.raises(ValidationError, match=message):
        annotation(issues=[{**FEES, "rationale": rationale}])


@pytest.mark.parametrize("repeated", [FEES, EXIT_MISSING])
def test_an_issue_repeated_in_other_words_is_a_duplicate(repeated):
    again = {**repeated, "rationale": "test rationale in other words", "confidence": "LOW"}
    with pytest.raises(ValidationError, match="duplicate expected issue"):
        annotation(issues=[FEES, EXIT_MISSING, again])


def test_one_entry_cannot_be_both_missing_and_located():
    with pytest.raises(ValidationError, match="cannot be both missing and located at a paragraph: COM-EXIT"):
        annotation(issues=[FEES, EXIT_MISSING, issue("COM-EXIT", 11)])


def test_one_entry_may_be_located_at_two_paragraphs():
    reference = compiled(issues=[issue("COM-FEES", 2), issue("COM-FEES", 3)])
    clauses = run().source.clauses
    assert [(i["playbookReference"], i["anchorId"]) for i in reference["issues"]] == [
        ("COM-FEES", clauses[2].id), ("COM-FEES", clauses[3].id)]


@pytest.mark.parametrize("value", [
    "11.10.2026", "2026-02-30", "2026-13-01", "20261011", "2026-10-11\n", " 2026-10-11", "2026-10-11T09:00",
    "2026-1-1", "tomorrow",
])
def test_annotated_on_must_be_a_real_calendar_date_of_ten_characters(value):
    with pytest.raises(ValidationError, match="annotatedOn must be an ISO date"):
        annotation(annotatedOn=value)


@pytest.mark.parametrize("value", ["2026-10-11", "2024-02-29", ""])
def test_annotated_on_accepts_a_calendar_date_and_the_empty_value_of_a_template(value):
    assert annotation(annotatedOn=value).annotatedOn == value


@pytest.mark.xfail(strict=True, reason="SOURCE DEFECT: annotatedOn accepts the ISO week date 2026-W41-1, "
                                       "which check passes and adjudication later refuses")
def test_annotated_on_refuses_an_iso_week_date():
    with pytest.raises(ValidationError, match="annotatedOn must be an ISO date"):
        annotation(annotatedOn="2026-W41-1")


@pytest.mark.parametrize("extra", [
    {"status": "INDEPENDENTLY_REVIEWED"}, {"status": "DRAFT"}, {"reviewerEvidence": "test-note-2026-10-11"},
    {"note": "not part of the schema"},
])
def test_an_annotation_has_no_status_no_evidence_and_no_other_extra_field(extra):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        annotation(**extra)


@pytest.mark.parametrize("extra", [{"severity": "HIGH"}, {"proposedAmendment": "test wording"}])
def test_an_issue_has_no_severity_and_no_amendment(extra):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        annotation(issues=[{**FEES, **extra}])


@pytest.mark.parametrize("change, message", [
    ({"confidence": "low"}, "'HIGH', 'MEDIUM' or 'LOW'"),
    ({"confidence": "CERTAIN"}, "'HIGH', 'MEDIUM' or 'LOW'"),
    ({"paragraph": -1}, "greater than or equal to 0"),
    ({"paragraph": "P2"}, "valid integer"),  # the listing shows P2, the template takes the number only
    ({"paragraph": 2.5}, "valid integer"),
    ({"playbookReference": ""}, "at least 1 character"),
])
def test_an_issue_with_a_malformed_field_is_refused(change, message):
    with pytest.raises(ValidationError, match=message):
        annotation(issues=[{**FEES, **change}])


@pytest.mark.parametrize("field", BINDING_HASHES)
def test_every_binding_hash_is_required(field):
    raw = filled()
    del raw[field]
    with pytest.raises(ValidationError, match=f"{field}\n  Field required"):
        Annotation.model_validate(raw)


@pytest.mark.parametrize("field", BINDING_HASHES)
@pytest.mark.parametrize("value", ["abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_a_binding_hash_must_be_a_sha256_hex_digest(field, value):
    with pytest.raises(ValidationError, match=field):
        annotation(**{field: value})


@pytest.mark.parametrize("field", BINDING_HASHES)
def test_only_the_source_register_hash_may_be_null(field):
    if field == "sourceRegisterSha256":
        assert annotation(sourceRegisterSha256=None).sourceRegisterSha256 is None
    else:
        with pytest.raises(ValidationError, match=field):
            annotation(**{field: None})


UNFILLED = [
    ({"annotator": ""}, "names no annotator; it looks like an unfilled template"),
    ({"annotator": " \t"}, "names no annotator; it looks like an unfilled template"),
    ({"annotatedOn": ""}, "the annotation has no date"),
    ({"sawModelOutput": None}, "does not answer whether model output was seen"),
]


@pytest.mark.parametrize("overrides, message", UNFILLED)
def test_a_half_filled_annotation_is_refused(overrides, message):
    half = annotation(**overrides)
    with pytest.raises(ValueError, match=message):
        require_filled(half)
    with pytest.raises(ValueError, match=message):
        compile_reference(half, CORPUS, annotation_sha256="a" * 64)


def test_a_filled_annotation_passes_the_filled_check():
    assert require_filled(annotation()) is None
    assert require_filled(annotation(sawModelOutput=True, issues=[])) is None


def test_every_untouched_template_is_refused_by_check_and_compile(pack):
    out, _ = pack
    templates = sorted((out / "templates").glob("*.annotation.json"))
    assert len(templates) == 6
    for path in templates:
        with pytest.raises(ValueError, match="looks like an unfilled template"):
            require_filled(Annotation.model_validate_json(path.read_text(encoding="utf-8")))
        for command in ("check", "compile"):
            with pytest.raises(ValueError, match="looks like an unfilled template"):
                main([command, str(path), "--corpus", str(CORPUS)])


def test_a_filled_annotation_with_zero_issues_is_valid_and_compiles_to_an_empty_draft():
    reference = compiled(issues=[])
    assert reference["issues"] == [] and reference["status"] == "DRAFT"
    assert reference["provenance"]["lowConfidenceIssues"] == 0
    CandidateReference.model_validate(reference)


def test_paragraph_numbers_become_the_recorder_anchors_of_the_committed_replay():
    clauses = run().source.clauses
    assert [clause.paragraph for clause in clauses] == list(range(13))
    located = [("COM-FEES", number) for number in range(13)]
    assert resolve_anchors(annotation(), CORPUS, located) == [clause.id for clause in clauses]


def test_a_missing_clause_resolves_to_no_anchor():
    anchors = resolve_anchors(annotation(), CORPUS, [("COM-EXIT", None), ("COM-FEES", 2), ("COM-SLA", None)])
    assert anchors == [None, run().source.clauses[2].id, None]


def test_an_anchor_is_bound_to_the_variant_as_well_as_to_the_paragraph():
    changed = Annotation.model_validate(filled(cell=("changed", "commercial")))
    assert resolve_anchors(changed, CORPUS, [("COM-FEES", 2)]) == [CHANGED_P2]
    # Paragraph 2 reads the same in both variants; the anchor still differs.
    assert CHANGED_P2 != run().source.clauses[2].id


def test_the_injected_appendix_is_paragraph_13_of_the_injection_variant():
    injection = Annotation.model_validate(filled(cell=("injection", "dora"), issues=[]))
    assert resolve_anchors(injection, CORPUS, [("DORA-EXIT", 13)]) == [INJECTION_P13]


@pytest.mark.parametrize("variant, last", [("base", 12), ("changed", 12), ("injection", 13)])
def test_the_last_paragraph_resolves_and_the_number_after_it_is_outside_the_document(variant, last):
    bound = Annotation.model_validate(filled(cell=(variant, "commercial")))
    (anchor,) = resolve_anchors(bound, CORPUS, [("COM-FEES", last)])
    assert re.fullmatch(r"[a-f0-9]{64}", anchor)
    with pytest.raises(ValueError, match=f"paragraph {last + 1} is outside the document"):
        resolve_anchors(bound, CORPUS, [("COM-FEES", last + 1)])


DOES_NOT_FIT = [
    ({"issues": [issue("COM-NOPE", 2)]}, "unknown playbook entry COM-NOPE"),
    ({"issues": [issue("COM-NOPE", None)]}, "unknown playbook entry COM-NOPE"),
    ({"issues": [issue("DORA-EXIT", None)]}, "unknown playbook entry DORA-EXIT"),  # an entry of the other playbook
    ({"issues": [FEES, issue("COM-SLA", 13)]}, "paragraph 13 is outside the document"),
    ({"issues": [issue("COM-FEES", 99)]}, "paragraph 99 is outside the document"),
    ({"documentSha256": DOCUMENTS["changed"]}, "bound to a different document"),
    ({"documentSha256": "0" * 64}, "bound to a different document"),
    ({"variant": "changed"}, "bound to a different document"),  # the base hash under another variant's name
    ({"variant": "nope"}, "unknown corpus variant nope"),
    ({"playbookSha256": PLAYBOOKS["dora"]}, "bound to a different playbook"),
    ({"playbookSha256": "0" * 64}, "bound to a different playbook"),
    ({"playbook": "dora"}, "bound to a different playbook"),  # the commercial hash under the other name
    ({"playbook": "nope"}, "bound to a different playbook"),
    ({"corpusManifestSha256": "0" * 64}, "different pack: corpusManifestSha256 no longer matches the corpus"),
    ({"guidelineSha256": "0" * 64}, "different pack: guidelineSha256 no longer matches the corpus"),
    ({"sourceRegisterSha256": "0" * 64}, "different pack: sourceRegisterSha256 no longer matches the corpus"),
    ({"sourceRegisterSha256": None}, "different pack: sourceRegisterSha256 no longer matches the corpus"),
]


@pytest.mark.parametrize("overrides, message", DOES_NOT_FIT)
def test_compile_refuses_an_annotation_that_does_not_fit_the_corpus(overrides, message):
    with pytest.raises(ValueError, match=message):
        compiled(**overrides)


@pytest.mark.parametrize("change, binding", [
    (change_instructions, "corpusManifestSha256"),
    (change_guideline, "guidelineSha256"),
    (change_register, "sourceRegisterSha256"),
    (remove_register, "sourceRegisterSha256"),
])
def test_an_annotation_made_before_the_corpus_changed_is_refused(corpus_copy, change, binding):
    before = Annotation.model_validate(filled(corpus_copy))
    assert compile_reference(before, corpus_copy, annotation_sha256="a" * 64)["status"] == "DRAFT"
    change(corpus_copy)
    with pytest.raises(ValueError, match=f"made from a different pack: {binding} no longer matches the corpus"):
        compile_reference(before, corpus_copy, annotation_sha256="a" * 64)
    after = Annotation.model_validate(filled(corpus_copy))
    reference = compile_reference(after, corpus_copy, annotation_sha256="a" * 64)
    assert reference["provenance"][binding] == file_hashes(corpus_copy)[binding] != getattr(before, binding)


def test_an_annotation_made_before_its_playbook_changed_is_refused(corpus_copy):
    before = Annotation.model_validate(filled(corpus_copy))
    other_cell = Annotation.model_validate(filled(corpus_copy, cell=("base", "dora"), issues=[]))
    change_playbook(corpus_copy)
    with pytest.raises(ValueError, match="bound to a different playbook"):
        compile_reference(before, corpus_copy, annotation_sha256="a" * 64)
    # The manifest pins every playbook, so the other cell's annotation is from an older pack too.
    with pytest.raises(ValueError, match="different pack: corpusManifestSha256 no longer matches"):
        compile_reference(other_cell, corpus_copy, annotation_sha256="a" * 64)


def test_compiled_reference_is_a_draft_with_evidence_rationales_and_provenance():
    assert compiled() == {
        "schema": "mycounsel.candidate-reference.v1",
        "sourceSha256": DOCUMENTS["base"],
        "playbookSha256": PLAYBOOKS["commercial"],
        "status": "DRAFT",
        "reviewerEvidence": "single annotation; annotation-sha256:" + "a" * 64,
        "issues": [
            {"playbookReference": "COM-FEES", "anchorId": run().source.clauses[2].id, "missingClause": False,
             "rationale": "Confidence HIGH: test rationale, not legal validation"},
            {"playbookReference": "COM-EXIT", "anchorId": None, "missingClause": True,
             "rationale": "Confidence MEDIUM: test rationale, not legal validation"},
        ],
        "provenance": {
            "route": "SINGLE_ANNOTATION",
            "corpusManifestSha256": sha((CORPUS / "manifest.json").read_bytes()),
            "guidelineSha256": sha((CORPUS / "annotation" / "GUIDELINE.md").read_bytes()),
            "sourceRegisterSha256": sha((CORPUS / "sources.json").read_bytes()),
            "lowConfidenceIssues": 0,
            "uncertaintiesRecorded": False,
            "annotatorSawModelOutput": False,
        },
    }


@pytest.mark.parametrize("confidences, low", [
    (("HIGH", "MEDIUM", "HIGH"), 0), (("LOW", "HIGH", "MEDIUM"), 1), (("HIGH", "LOW", "LOW"), 2),
    (("LOW", "LOW", "LOW"), 3),
])
def test_provenance_counts_the_issues_marked_low_and_each_rationale_states_its_confidence(confidences, low):
    places = [("COM-FEES", 2), ("COM-SLA", 4), ("COM-EXIT", None)]
    issues = [issue(entry, paragraph, confidence) for (entry, paragraph), confidence in zip(places, confidences)]
    reference = compiled(issues=issues)
    assert reference["provenance"]["lowConfidenceIssues"] == low
    assert [i["rationale"] for i in reference["issues"]] == [
        f"Confidence {confidence}: test rationale, not legal validation" for confidence in confidences]


def test_a_rationale_is_trimmed_before_the_confidence_is_put_in_front():
    reference = compiled(issues=[issue("COM-FEES", 2, "LOW", "  test rationale with space around it \n")])
    assert reference["issues"][0]["rationale"] == "Confidence LOW: test rationale with space around it"


@pytest.mark.parametrize("uncertainties, recorded", [
    ("", False), ("  \n", False), ("Test doubt about how an entry is framed", True),
])
def test_provenance_says_whether_doubts_were_written_down(uncertainties, recorded):
    assert compiled(uncertainties=uncertainties)["provenance"]["uncertaintiesRecorded"] is recorded


@pytest.mark.parametrize("saw", [True, False])
def test_provenance_keeps_the_annotators_answer_on_model_output(saw):
    reference = compiled(sawModelOutput=saw)
    assert reference["provenance"]["annotatorSawModelOutput"] is saw
    assert reference["status"] == "DRAFT"


def test_one_annotation_never_compiles_to_an_independently_reviewed_reference():
    reference = compiled()
    assert reference["status"] == "DRAFT" and reference["provenance"]["route"] == "SINGLE_ANNOTATION"
    with pytest.raises(ValidationError, match="independent review needs two annotations and written adjudication"):
        CandidateReference.model_validate({**reference, "status": "INDEPENDENTLY_REVIEWED"})


# The replay holds four findings: COM-FEES at P2 twice, an unknown entry at P2, COM-EXIT as a missing clause.
@pytest.mark.parametrize("issues, counts, precision, recall, entry_level", [
    ([FEES, EXIT_MISSING], (2, 2, 0), 0.5, 1.0, (2, 0, 0)),
    ([FEES, issue("COM-SLA", 4)], (1, 3, 1), 0.25, 0.5, (1, 1, 1)),
    ([issue("COM-FEES", 3), issue("COM-EXIT", 11)], (0, 4, 2), 0.0, 0.0, (2, 0, 0)),
    ([], (0, 4, 0), 0.0, None, (0, 2, 0)),
])
def test_a_compiled_reference_scores_the_committed_replay(issues, counts, precision, recall, entry_level):
    reference = CandidateReference.model_validate(compiled(issues=issues))
    match = evaluate_candidates(run(), reference)["issueMatch"]
    assert (match["truePositives"], match["falsePositives"], match["falseNegatives"]) == counts
    assert (match["precision"], match["recall"]) == (precision, recall)
    entries = match["entryLevel"]
    assert (entries["truePositives"], entries["falsePositives"], entries["falseNegatives"]) == entry_level
    assert (match["referenceStatus"], match["referenceRoute"]) == ("DRAFT", "SINGLE_ANNOTATION")
    assert match["referenceEvidence"] == "single annotation; annotation-sha256:" + "a" * 64
    assert match["independentReviewClaimVerified"] is False


def corrupt_playbook(copy: Path) -> None:
    (copy / "commercial.json").write_text("{}", encoding="utf-8")


def swap_document(copy: Path) -> None:
    shutil.copyfile(copy / "ict-injection.docx", copy / "ict-base.docx")


def list_a_variant_twice(copy: Path) -> None:
    edit_json(copy / "manifest.json", lambda manifest: manifest["documents"].append(manifest["documents"][0]))


@pytest.mark.parametrize("change, message", [
    (corrupt_playbook, "corpus playbook commercial does not match its manifest hash"),
    (swap_document, "corpus document ict-base.docx does not match its manifest hash"),
    (list_a_variant_twice, "corpus variants must be unique"),
])
def test_corpus_loader_refuses_a_corpus_that_differs_from_its_manifest(corpus_copy, change, message):
    assert load_corpus(corpus_copy).document("injection").sha256 == DOCUMENTS["injection"]
    change(corpus_copy)
    with pytest.raises(ValueError, match=message):
        load_corpus(corpus_copy)


def test_the_committed_register_covers_exactly_the_statutory_playbook_entries():
    register = load_source_register(CORPUS)
    assert [source.id for source in register.sources] == ["SRC-DORA-ART30"]
    cited = sorted(register.sources[0].usedBy)
    assert cited == ["DORA-ASSISTANCE", "DORA-AUDIT", "DORA-EXIT", "DORA-LOCATIONS", "DORA-RETURN", "DORA-SLA"]
    statutory = sorted(entry["id"] for name in PLAYBOOKS for entry in read_json(CORPUS / f"{name}.json")["entries"]
                       if entry["category"] == "STATUTORY_REQUIREMENT")
    assert statutory == cited == sorted(register.sources[0].pinpoints)


def test_snapshot_text_is_what_follows_the_first_separator_without_the_final_newline():
    assert snapshot_text("Test header\nFetched: never\n---\nTest provision text.\n") == "Test provision text."
    assert snapshot_text("Test header\n---\nfirst part\n---\nsecond part\n\n") == "first part\n---\nsecond part"


@pytest.mark.parametrize("raw", ["Test provision text without a header.\n", "Test header --- test text\n", ""])
def test_snapshot_text_refuses_a_file_without_the_header_separator(raw):
    with pytest.raises(ValueError, match="snapshot has no header separator"):
        snapshot_text(raw)


def test_the_committed_snapshot_hashes_to_the_value_in_the_register_and_in_its_own_header():
    raw = (CORPUS / SNAPSHOT).read_text(encoding="utf-8")
    registered = read_json(CORPUS / "sources.json")["sources"][0]["snapshotTextSha256"]
    header = raw.split("\n---\n")[0].splitlines()
    assert f"SHA-256 of the provision text below the separator: {registered}" in header
    assert sha(snapshot_text(raw)) == registered
    assert snapshot_text(raw).startswith("Article 30 Key contractual provisions 1. ")
    assert "SOURCE SNAPSHOT" not in snapshot_text(raw)


def test_a_snapshot_whose_text_was_edited_is_refused(corpus_copy):
    path = corpus_copy / SNAPSHOT
    text = path.read_text(encoding="utf-8")
    assert text.count("at no additional cost") == 1
    path.write_text(text.replace("at no additional cost", "at a cost agreed later"), encoding="utf-8")
    with pytest.raises(ValueError, match=f"snapshot {SNAPSHOT} does not match the hash registered for SRC-DORA-ART30"):
        load_source_register(corpus_copy)


def test_a_corpus_with_an_edited_snapshot_binds_nothing_and_builds_no_pack(corpus_copy, tmp_path):
    path = corpus_copy / SNAPSHOT
    path.write_text(path.read_text(encoding="utf-8") + "Test sentence added to the provision text.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match the hash registered"):
        corpus_bindings(corpus_copy)
    with pytest.raises(ValueError, match="does not match the hash registered"):
        build_pack(corpus_copy, tmp_path / "pack")
    assert not (tmp_path / "pack").exists()


def test_an_edit_to_the_snapshot_header_leaves_the_registered_text_hash_valid(corpus_copy):
    change_snapshot_header(corpus_copy)
    assert load_source_register(corpus_copy).sources[0].id == "SRC-DORA-ART30"


def test_a_snapshot_without_the_header_separator_is_refused(corpus_copy):
    path = corpus_copy / SNAPSHOT
    # The provision text alone: its hash would match, the header and separator are gone.
    path.write_text(snapshot_text(path.read_text(encoding="utf-8")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot has no header separator"):
        load_source_register(corpus_copy)


def test_a_source_cited_for_an_entry_in_no_playbook_is_refused(corpus_copy):
    edit_source(corpus_copy, lambda source: cite(source, "DORA-NOPE"))
    with pytest.raises(ValueError, match="source SRC-DORA-ART30 is cited for unknown playbook entries: DORA-NOPE"):
        load_source_register(corpus_copy)


@pytest.mark.parametrize("change", [
    lambda source: source["pinpoints"].pop("DORA-EXIT"),
    lambda source: source["pinpoints"].update({"COM-FEES": "Test pinpoint"}),
    lambda source: source["pinpoints"].clear(),
    lambda source: source["usedBy"].append("COM-FEES"),
], ids=["one missing", "one for an entry that does not cite", "none", "a citing entry without one"])
def test_pinpoints_must_cover_exactly_the_citing_entries(corpus_copy, change):
    edit_source(corpus_copy, change)
    with pytest.raises(ValueError, match="source SRC-DORA-ART30 needs exactly one pinpoint per citing playbook entry"):
        load_source_register(corpus_copy)


@pytest.mark.xfail(strict=True, reason="SOURCE DEFECT: a blank pinpoint counts as the pinpoint of a citing playbook entry")
def test_a_blank_pinpoint_is_refused(corpus_copy):
    edit_source(corpus_copy, lambda source: source["pinpoints"].update({"DORA-EXIT": " "}))
    with pytest.raises(ValueError):
        load_source_register(corpus_copy)


def test_a_statutory_entry_without_a_registered_source_is_refused(corpus_copy):
    edit_source(corpus_copy, lambda source: uncite(source, "DORA-EXIT"))
    with pytest.raises(ValueError, match="statutory playbook entries without a registered source: DORA-EXIT$"):
        load_source_register(corpus_copy)


def test_a_register_that_lags_a_new_statutory_entry_is_refused(corpus_copy, tmp_path):
    add_entry(corpus_copy, "dora", "DORA-TEST", "STATUTORY_REQUIREMENT")
    with pytest.raises(ValueError, match="statutory playbook entries without a registered source: DORA-TEST$"):
        load_source_register(corpus_copy)
    with pytest.raises(ValueError, match="without a registered source"):
        build_pack(corpus_copy, tmp_path / "pack")


def test_a_new_entry_that_is_not_statutory_needs_no_source(corpus_copy):
    add_entry(corpus_copy, "commercial", "COM-TEST", "COMMERCIAL_RISK")
    assert load_source_register(corpus_copy) is not None


def test_a_corpus_without_a_register_returns_none_and_binds_a_null_register_hash(corpus_copy):
    remove_register(corpus_copy)
    assert load_source_register(corpus_copy) is None
    assert corpus_bindings(corpus_copy) == {
        "corpusManifestSha256": sha((corpus_copy / "manifest.json").read_bytes()),
        "guidelineSha256": sha((corpus_copy / "annotation" / "GUIDELINE.md").read_bytes()),
        "sourceRegisterSha256": None,
    }


def test_a_pack_built_without_a_register_has_no_source_files_and_null_bound_templates(corpus_copy, tmp_path):
    remove_register(corpus_copy)
    out = tmp_path / "pack"
    manifest = build_pack(corpus_copy, out)
    assert sorted(manifest["files"]) == sorted(name for name in PACK_FILES if not name.startswith("sources/"))
    assert manifest["sourceRegisterSha256"] is None
    for path in (out / "templates").glob("*.annotation.json"):
        assert read_json(path)["sourceRegisterSha256"] is None
    verify_pack(out, corpus_copy)
    reference = compile_reference(Annotation.model_validate(filled(corpus_copy)), corpus_copy,
                                  annotation_sha256="a" * 64)
    assert reference["provenance"]["sourceRegisterSha256"] is None


def test_pack_holds_exactly_the_listed_files_and_its_manifest(pack):
    out, manifest = pack
    assert files_in(out) == sorted([*PACK_FILES, "MANIFEST.json"])
    assert sorted(manifest["files"]) == sorted(PACK_FILES)
    assert sorted(path.name for path in out.iterdir()) == [
        "GUIDELINE.md", "MANIFEST.json", "documents", "instructions.md", "playbooks", "sources", "templates"]


def test_manifest_hashes_every_file_and_carries_the_bindings_and_the_withheld_list(pack):
    out, manifest = pack
    assert read_json(out / "MANIFEST.json") == manifest
    assert list(manifest) == [
        "schema", "corpusManifestSha256", "guidelineSha256", "sourceRegisterSha256", "files", "withheld"]
    assert manifest["schema"] == "mycounsel.annotation-pack.v1"
    assert {name: manifest[name] for name in file_hashes()} == file_hashes()
    assert manifest["files"] == {name: sha((out / name).read_bytes()) for name in PACK_FILES}
    assert len(manifest["withheld"]) == 5
    for name in ("replay-run.json", "replay-score.json", "README.md", "build_fixtures.py"):
        assert sum(entry.startswith(name) for entry in manifest["withheld"]) == 1
        assert name not in {Path(relative).name for relative in files_in(out)}
    assert manifest["withheld"][4] == "any model output, experiment report or earlier annotation"


def test_pack_copies_documents_playbooks_sources_and_guideline_byte_for_byte(pack):
    out, _ = pack
    copies = {
        "GUIDELINE.md": "annotation/GUIDELINE.md", "sources/sources.json": "sources.json", SNAPSHOT: SNAPSHOT,
        **{f"documents/ict-{variant}.docx": f"ict-{variant}.docx" for variant in DOCUMENTS},
        **{f"playbooks/{name}.json": f"{name}.json" for name in PLAYBOOKS},
    }
    assert len(copies) == 8
    for in_pack, in_corpus in copies.items():
        assert (out / in_pack).read_bytes() == (CORPUS / in_corpus).read_bytes(), in_pack
    for variant, expected in DOCUMENTS.items():
        assert sha((out / "documents" / f"ict-{variant}.docx").read_bytes()) == expected
    assert (out / "instructions.md").read_text(encoding="utf-8") == (
        "# Business instructions\n\n" + MANIFEST["instructions"] + "\n")


@pytest.mark.parametrize("variant", ["base", "changed", "injection"])
@pytest.mark.parametrize("playbook", ["commercial", "dora"])
def test_every_template_is_valid_unfilled_and_bound_to_the_files_of_its_pack(pack, variant, playbook):
    out, _ = pack
    raw = read_json(out / "templates" / f"{variant}-{playbook}.annotation.json")
    Annotation.model_validate(raw)
    assert raw == {
        "schema": "mycounsel.candidate-annotation.v1", "variant": variant, "playbook": playbook,
        "documentSha256": sha((out / "documents" / f"ict-{variant}.docx").read_bytes()),
        "playbookSha256": sha((out / "playbooks" / f"{playbook}.json").read_bytes()),
        "corpusManifestSha256": sha((CORPUS / "manifest.json").read_bytes()),
        "guidelineSha256": sha((out / "GUIDELINE.md").read_bytes()),
        "sourceRegisterSha256": sha((out / "sources" / "sources.json").read_bytes()),
        "annotator": "", "annotatedOn": "", "sawModelOutput": None, "issues": [], "uncertainties": "",
    }
    assert list(raw) == TEMPLATE_FIELDS


@pytest.mark.parametrize("variant, count", [("base", 13), ("changed", 13), ("injection", 14)])
def test_a_paragraph_listing_numbers_every_paragraph_of_its_document_from_zero(pack, variant, count):
    out, _ = pack
    lines = (out / "documents" / f"{variant}.paragraphs.md").read_text(encoding="utf-8").splitlines()
    numbered = [line for line in lines if re.match(r"P\d+: ", line)]
    paragraphs = document_paragraphs((out / "documents" / f"ict-{variant}.docx").read_bytes())
    assert len(numbered) == count
    assert numbered == [f"P{number}: {text}" for number, text in enumerate(paragraphs)]
    assert lines[0] == f"# ict-{variant}.docx" and lines[2] == f"SHA-256 {DOCUMENTS[variant]}"
    assert "Paragraph numbers start at 0. In a template, enter the number only: 2 for P2." in lines


def test_paragraph_listing_numbers_equal_the_recorder_anchors(pack):
    out, _ = pack
    listing = (out / "documents" / "base.paragraphs.md").read_text(encoding="utf-8").splitlines()
    numbered = {int(found[1]): found[2] for line in listing if (found := re.fullmatch(r"P(\d+): (.*)", line))}
    clauses = run().source.clauses
    assert numbered == {clause.paragraph: clause.text for clause in clauses}
    template = read_json(out / "templates" / "base-commercial.annotation.json")
    bound = Annotation.model_validate({**template, "annotator": "Test Annotator A"})
    located = [("COM-FEES", number) for number in sorted(numbered)]
    assert resolve_anchors(bound, CORPUS, located) == [clause.id for clause in clauses]


@pytest.mark.parametrize("name", ["commercial", "dora"])
def test_a_playbook_listing_shows_every_entry_with_its_category_and_requirement(pack, name):
    out, _ = pack
    lines = (out / "playbooks" / f"{name}.md").read_text(encoding="utf-8").splitlines()
    entries = read_json(CORPUS / f"{name}.json")["entries"]
    assert len(entries) == 6
    assert lines[:6] == [f"# Playbook {name}", "", f"SHA-256 {PLAYBOOKS[name]}", "",
                         "| ID | Category | Requirement |", "| --- | --- | --- |"]
    assert lines[6:] == [f"| {e['id']} | {e['category']} | {e['requirement']} |" for e in entries]


def test_the_commercial_listing_starts_with_the_fees_entry(pack):
    out, _ = pack
    assert (out / "playbooks" / "commercial.md").read_text(encoding="utf-8").splitlines()[6] == (
        "| COM-FEES | NEGOTIATED_PREFERENCE | Require an agreed limit on fee changes, reasonable advance notice "
        "and an exit option if the change is rejected. |")


def test_build_refuses_a_guideline_other_than_the_one_in_the_corpus(tmp_path):
    other = tmp_path / "GUIDELINE.md"
    other.write_text("# Test guideline, not the one in the corpus\n", encoding="utf-8")
    with pytest.raises(ValueError, match="the pack is built from the corpus guideline"):
        build_pack(CORPUS, tmp_path / "pack", other)
    assert not (tmp_path / "pack").exists()
    assert build_pack(CORPUS, tmp_path / "pack", CORPUS / "annotation" / "GUIDELINE.md")["files"]


def test_a_rebuild_replaces_an_older_pack_completely(pack):
    out, manifest = pack
    (out / "templates" / "stray.txt").write_text("Test file left over from an older build", encoding="utf-8")
    (out / "GUIDELINE.md").write_text("Test edit", encoding="utf-8")
    assert build_pack(CORPUS, out) == manifest
    assert files_in(out) == sorted([*PACK_FILES, "MANIFEST.json"])
    verify_pack(out, CORPUS)


@pytest.mark.xfail(strict=True, reason="SOURCE DEFECT: build deletes any existing --out folder, "
                                       "also one that holds returned annotations")
def test_build_does_not_delete_a_folder_that_is_not_an_annotation_pack(tmp_path):
    returned = tmp_path / "returned"
    returned.mkdir()
    kept = write(returned / "base-commercial.annotation.json", filled())
    with pytest.raises((ValueError, FileExistsError)):
        build_pack(CORPUS, returned)
    assert kept.exists()


def test_two_builds_of_one_corpus_are_identical(tmp_path):
    first, second = build_pack(CORPUS, tmp_path / "one"), build_pack(CORPUS, tmp_path / "two")
    assert first == second
    for relative in files_in(tmp_path / "one"):
        assert (tmp_path / "one" / relative).read_bytes() == (tmp_path / "two" / relative).read_bytes(), relative


def test_the_committed_pack_verifies_against_the_committed_corpus():
    manifest = verify_pack(CORPUS / "annotation-pack", CORPUS)
    assert sorted(manifest["files"]) == sorted(PACK_FILES)
    assert {name: manifest[name] for name in file_hashes()} == file_hashes()


def test_the_committed_pack_is_byte_for_byte_what_the_corpus_builds(pack):
    out, _ = pack
    committed = CORPUS / "annotation-pack"
    assert files_in(committed) == files_in(out)
    for relative in files_in(out):
        assert (committed / relative).read_bytes() == (out / relative).read_bytes(), relative


def text_files(out: Path) -> str:
    """Every text file of a pack. Its Word files are byte copies of the pinned corpus documents."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(out.rglob("*"))
                     if path.is_file() and path.suffix != ".docx")


def everything_readable(out: Path) -> str:
    """The text files and every part of every Word package."""
    parts = [text_files(out)]
    for path in sorted(out.rglob("*.docx")):
        with ZipFile(path) as package:
            parts += [package.read(name).decode("utf-8") for name in package.namelist()]
    return "\n".join(parts)


@functools.cache
def corpus_content() -> tuple[str, ...]:
    """What an annotator is meant to receive: paragraphs, playbook entries, instructions, register, snapshot."""
    units = {MANIFEST["instructions"], (CORPUS / "sources.json").read_text(encoding="utf-8"),
             (CORPUS / SNAPSHOT).read_text(encoding="utf-8")}
    for document in MANIFEST["documents"]:
        units.update(document_paragraphs((CORPUS / document["filename"]).read_bytes()))
    for name in PLAYBOOKS:
        raw = (CORPUS / f"{name}.json").read_text(encoding="utf-8")
        units.add(raw)
        for entry in json.loads(raw)["entries"]:
            units.update((entry["id"], entry["category"], entry["requirement"]))
    return tuple(sorted(units, key=len, reverse=True))


def word_sequences(text: str, length: int) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[start:start + length]) for start in range(len(words) - length + 1)}


def notes(text: str) -> set[tuple[str, ...]]:
    """Eight-word sequences of a text once the corpus content is cut out of it."""
    for unit in corpus_content():
        text = text.replace(unit, "\x00")
    return set().union(*(word_sequences(part, 8) for part in text.split("\x00")))


def shared_notes(pack_text: str, withheld_text: str) -> list[str]:
    shared = (notes(pack_text) & notes(withheld_text)) - word_sequences(SHARED_ON_PURPOSE, 8)
    return sorted(" ".join(words) for words in shared)


def builder_lines_in(pack_text: str) -> list[str]:
    lines = {line.strip() for line in (CORPUS / "build_fixtures.py").read_text(encoding="utf-8").splitlines()}
    return sorted(line for line in lines if len(line) >= 12 and line in pack_text)


def strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [found for child in value.values() for found in strings(child)]
    if isinstance(value, list):
        return [found for child in value for found in strings(child)]
    return []


def field_names(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(field_names(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(field_names(child) for child in value))
    return set()


def withheld_values(name: str) -> set[str]:
    """String values of a withheld JSON file, without the corpus content an annotator receives anyway."""
    received = "\n".join(corpus_content()) + (CORPUS / "manifest.json").read_text(encoding="utf-8")
    return {value for value in strings(read_json(CORPUS / name)) if value and value not in received}


def withheld_fields(name: str) -> set[str]:
    """camelCase field names of a withheld JSON file, without the fields a template carries itself."""
    names = {field for field in field_names(read_json(CORPUS / name)) if field != field.lower()}
    return names - set(TEMPLATE_FIELDS) - ISSUE_FIELDS


def leaked(pack_text: str, name: str) -> list[str]:
    return sorted(item for item in withheld_values(name) | withheld_fields(name) if item in pack_text)


def test_pack_contains_no_value_or_field_of_the_withheld_replay_recording(pack):
    out, _ = pack
    artifact = run()
    values = withheld_values("replay-run.json")
    assert {finding.explanation for finding in artifact.findings} <= values
    assert {clause.id for clause in artifact.source.clauses} <= values
    assert {"UNSUPPORTED-ENTRY", "hand-authored-replay-fixture", "CONTRACT_PLAYBOOK_REFERENCE"} <= values
    assert {"anchorId", "insertionAnchorId", "proposedAmendment", "codeRevision"} <= withheld_fields("replay-run.json")
    assert leaked(everything_readable(out), "replay-run.json") == []


def test_pack_contains_no_field_or_value_of_the_withheld_replay_score(pack):
    out, _ = pack
    fields = withheld_fields("replay-score.json")
    assert {"recordingSha256", "findingCount", "duplicateCount", "quotationValid", "playbookReferenceValid",
            "allFindingsValid", "issueMatch", "evidenceValid", "quotationSubstantive"} <= fields
    assert "Native output has no severity field" in withheld_values("replay-score.json")
    assert leaked(everything_readable(out), "replay-score.json") == []


@pytest.mark.parametrize("name", ["README.md", "build_fixtures.py"])
def test_pack_shares_no_eight_word_note_with_the_withheld_readme_or_fixture_builder(pack, name):
    out, _ = pack
    withheld = (CORPUS / name).read_text(encoding="utf-8")
    assert len(notes(withheld)) > 100
    assert shared_notes(text_files(out), withheld) == []


def test_pack_contains_no_line_of_the_withheld_fixture_builder(pack):
    out, _ = pack
    assert builder_lines_in(everything_readable(out)) == []
    assert builder_lines_in((CORPUS / "build_fixtures.py").read_text(encoding="utf-8")) != []


def test_the_blindness_comparisons_find_a_note_planted_from_each_withheld_file(pack):
    out, _ = pack
    readme = (CORPUS / "README.md").read_text(encoding="utf-8")
    construction = [part for part in readme.split("\n\n") if "`changed` document" in part]
    slicing = [line.strip() for line in (CORPUS / "build_fixtures.py").read_text(encoding="utf-8").splitlines()
               if "PARAGRAPHS[" in line]
    explanation = run().findings[0].explanation
    assert len(construction) == 1 and slicing
    assert shared_notes(text_files(out), readme) == [] and builder_lines_in(text_files(out)) == []
    with (out / "GUIDELINE.md").open("a", encoding="utf-8") as guideline:
        guideline.write("\n".join([construction[0], slicing[0], explanation, '"quotationValid": 3']) + "\n")
    planted = text_files(out)
    assert shared_notes(planted, readme) != []
    assert builder_lines_in(planted) == [slicing[0]]
    assert leaked(planted, "replay-run.json") == [explanation]
    assert leaked(planted, "replay-score.json") == ["quotationValid"]


def test_no_template_holds_an_issue_and_no_file_outside_playbooks_and_sources_names_an_entry(pack):
    out, _ = pack
    entries = [entry["id"] for name in PLAYBOOKS for entry in read_json(CORPUS / f"{name}.json")["entries"]]
    assert len(entries) == 12
    for relative in files_in(out):
        if relative.endswith(".docx") or relative.split("/")[0] in ("playbooks", "sources"):
            continue
        text = (out / relative).read_text(encoding="utf-8")
        assert [entry for entry in entries if entry in text] == [], relative
    for path in (out / "templates").glob("*.annotation.json"):
        assert read_json(path)["issues"] == []


def guideline_example() -> dict:
    guideline = (CORPUS / "annotation" / "GUIDELINE.md").read_text(encoding="utf-8")
    (block,) = re.findall(r"```json\n(.*?)\n```", guideline, flags=re.S)
    return json.loads(block)


def test_guideline_example_shows_the_fields_an_annotator_fills_with_one_located_and_one_missing_issue():
    example = guideline_example()
    assert list(example) == TEMPLATE_FIELDS[8:]
    assert all(set(shown) == ISSUE_FIELDS for shown in example["issues"])
    assert [(shown["paragraph"] is None, shown["missingClause"]) for shown in example["issues"]] == [
        (False, False), (True, True)]


def test_guideline_example_names_no_playbook_entry_of_the_corpus():
    entries = {entry["id"] for name in PLAYBOOKS for entry in read_json(CORPUS / f"{name}.json")["entries"]}
    assert len(entries) == 12
    for shown in guideline_example()["issues"]:
        assert shown["playbookReference"] not in entries
        assert not any(entry in shown["playbookReference"] for entry in entries)


def test_guideline_example_points_at_no_paragraph_of_any_corpus_document():
    lengths = [len(document_paragraphs((CORPUS / d["filename"]).read_bytes())) for d in MANIFEST["documents"]]
    assert lengths == [13, 13, 14]
    numbers = [shown["paragraph"] for shown in guideline_example()["issues"] if shown["paragraph"] is not None]
    assert numbers and all(number >= max(lengths) for number in numbers)


def test_guideline_example_shares_no_four_word_sequence_with_a_paragraph_or_a_requirement():
    corpus_words = set()
    for document in MANIFEST["documents"]:
        for paragraph in document_paragraphs((CORPUS / document["filename"]).read_bytes()):
            corpus_words |= word_sequences(paragraph, 4)
    for name in PLAYBOOKS:
        for entry in read_json(CORPUS / f"{name}.json")["entries"]:
            corpus_words |= word_sequences(entry["requirement"], 4)
    assert len(corpus_words) > 500
    example = guideline_example()
    for text in [example["annotator"], example["uncertainties"], *(shown["rationale"] for shown in example["issues"])]:
        assert word_sequences(text, 4) & corpus_words == set()


def test_a_template_filled_with_the_guideline_example_is_refused(pack):
    out, _ = pack
    example = guideline_example()
    unknown = re.escape(example["issues"][0]["playbookReference"])
    templates = sorted((out / "templates").glob("*.annotation.json"))
    assert len(templates) == 6
    for path in templates:
        shaped = Annotation.model_validate({**read_json(path), **example})
        with pytest.raises(ValueError, match=f"unknown playbook entry {unknown}"):
            compile_reference(shaped, CORPUS, annotation_sha256="a" * 64)


def edit_a_file(out: Path) -> None:
    (out / "instructions.md").write_text("# Business instructions\n\nTest edit.\n", encoding="utf-8")


def add_a_file(out: Path) -> None:
    (out / "documents" / "notes.md").write_text("Test note, not an annotation.\n", encoding="utf-8")


def remove_a_file(out: Path) -> None:
    (out / "templates" / "base-dora.annotation.json").unlink()


def add_a_nested_manifest(out: Path) -> None:
    (out / "documents" / "MANIFEST.json").write_text('{"note": "Test hint, not an annotation."}\n', encoding="utf-8")


@pytest.mark.parametrize("change, message", [
    (edit_a_file, "pack file instructions.md differs from its manifest hash"),
    (add_a_file, r"pack files differ from the manifest: \['documents/notes.md'\]"),
    (remove_a_file, r"pack files differ from the manifest: \['templates/base-dora.annotation.json'\]"),
    (add_a_nested_manifest, r"pack files differ from the manifest: \['documents/MANIFEST.json'\]"),
])
def test_verify_without_a_corpus_refuses_a_pack_that_differs_from_its_manifest(pack, change, message):
    out, manifest = pack
    assert verify_pack(out) == manifest
    change(out)
    with pytest.raises(ValueError, match=message):
        verify_pack(out)
    with pytest.raises(ValueError, match=message):
        verify_pack(out, CORPUS)


def test_verify_refuses_a_manifest_of_another_schema(pack):
    out, _ = pack
    edit_json(out / "MANIFEST.json", lambda manifest: manifest.update(schema="mycounsel.synthetic-corpus.v1"))
    with pytest.raises(ValueError, match="not an annotation pack manifest"):
        verify_pack(out)


def test_a_file_edited_together_with_its_manifest_line_is_refused_only_against_the_corpus(pack):
    out, _ = pack
    prefill(out)
    # Against its own manifest the pack is consistent. That is the stated limit of the check without a corpus.
    assert "Test hint" in (out / "templates" / "base-commercial.annotation.json").read_text(encoding="utf-8")
    verify_pack(out)
    with pytest.raises(ValueError, match=STALE):
        verify_pack(out, CORPUS)


@pytest.mark.parametrize("change", [
    lambda manifest: manifest.update(withheld=[]),
    lambda manifest: manifest.update(note="Test hint, not an annotation."),
    lambda manifest: manifest.update(guidelineSha256="0" * 64),
], ids=["withheld list emptied", "note added", "binding changed"])
def test_a_manifest_that_differs_from_a_fresh_build_is_refused_against_the_corpus(pack, change):
    out, _ = pack
    edit_json(out / "MANIFEST.json", change)
    verify_pack(out)
    with pytest.raises(ValueError, match=STALE):
        verify_pack(out, CORPUS)


@pytest.mark.xfail(strict=True, reason="SOURCE DEFECT: verify compares parsed manifests, so MANIFEST.json can carry "
                                       "text a fresh build does not write and still verify and bundle")
def test_verify_refuses_a_manifest_file_with_text_a_fresh_build_does_not_write(pack):
    out, _ = pack
    path = out / "MANIFEST.json"
    text = path.read_text(encoding="utf-8")
    # A second "withheld" key before the real one: a JSON parser keeps the last, a reader sees both.
    path.write_text(text.replace("{\n", '{\n  "withheld": ["Test hint, not an annotation."],\n', 1), encoding="utf-8")
    assert "Test hint" in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        verify_pack(out, CORPUS)


@pytest.mark.parametrize("change", [
    change_guideline, change_playbook, change_register, change_instructions, change_snapshot_header,
])
def test_a_pack_built_before_the_corpus_changed_is_refused(corpus_copy, tmp_path, change):
    out = tmp_path / "pack"
    build_pack(corpus_copy, out)
    verify_pack(out, corpus_copy)
    change(corpus_copy)
    verify_pack(out)
    with pytest.raises(ValueError, match=STALE):
        verify_pack(out, corpus_copy)
    assert verify_pack(out, CORPUS)["files"]


def test_bundle_is_deterministic_with_the_manifest_first_and_fixed_timestamps(pack, tmp_path):
    out, _ = pack
    first, second = tmp_path / "a" / "pack.zip", tmp_path / "b" / "nested" / "pack.zip"
    assert bundle_pack(out, first, CORPUS) == bundle_pack(out, second, CORPUS) == sha(first.read_bytes())
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert archive.namelist() == [
            "annotation-pack/MANIFEST.json", *(f"annotation-pack/{name}" for name in sorted(PACK_FILES))]
        for info in archive.infolist():
            assert info.date_time == (2026, 1, 1, 0, 0, 0)
            assert archive.read(info) == (out / info.filename.removeprefix("annotation-pack/")).read_bytes()


def test_bundle_refuses_an_edited_pack_and_writes_no_archive(pack, tmp_path):
    out, _ = pack
    edit_a_file(out)
    with pytest.raises(ValueError, match="pack file instructions.md differs from its manifest hash"):
        bundle_pack(out, tmp_path / "bundle" / "pack.zip", CORPUS)
    assert not (tmp_path / "bundle").exists()


def test_bundle_refuses_a_pack_edited_together_with_its_manifest(pack, tmp_path):
    out, _ = pack
    prefill(out)
    with pytest.raises(ValueError, match=STALE):
        bundle_pack(out, tmp_path / "bundle" / "pack.zip", CORPUS)
    assert not (tmp_path / "bundle").exists()


def test_bundle_refuses_a_pack_built_before_the_guideline_changed(corpus_copy, tmp_path):
    out = tmp_path / "pack"
    build_pack(corpus_copy, out)
    change_guideline(corpus_copy)
    with pytest.raises(ValueError, match=STALE):
        bundle_pack(out, tmp_path / "bundle" / "pack.zip", corpus_copy)
    assert not (tmp_path / "bundle").exists()


def test_cli_build_verify_and_bundle_report_what_they_did(tmp_path, capsys):
    out, archive = tmp_path / "pack", tmp_path / "bundle" / "pack.zip"
    main(["build", "--corpus", str(CORPUS), "--out", str(out)])
    assert capsys.readouterr().out == f"Wrote 20 pack files to {out}. Withheld: 5 categories.\n"
    assert files_in(out) == sorted([*PACK_FILES, "MANIFEST.json"])
    main(["verify", "--corpus", str(CORPUS), "--pack", str(out)])
    assert capsys.readouterr().out == "Pack verified: 20 files match their hashes and the corpus.\n"
    main(["bundle", "--corpus", str(CORPUS), "--pack", str(out), "--out", str(archive)])
    assert capsys.readouterr().out == f"Wrote {archive} (SHA-256 {sha(archive.read_bytes())}).\n"


def test_cli_verify_and_bundle_hold_the_pack_against_the_corpus(corpus_copy, tmp_path):
    out = tmp_path / "pack"
    main(["build", "--corpus", str(corpus_copy), "--out", str(out)])
    change_guideline(corpus_copy)
    with pytest.raises(ValueError, match=STALE):
        main(["verify", "--corpus", str(corpus_copy), "--pack", str(out)])
    with pytest.raises(ValueError, match=STALE):
        main(["bundle", "--corpus", str(corpus_copy), "--pack", str(out), "--out", str(tmp_path / "pack.zip")])
    assert not (tmp_path / "pack.zip").exists()


def test_cli_verify_defaults_to_the_committed_pack_and_corpus(monkeypatch, capsys):
    monkeypatch.chdir(REPO)
    main(["verify"])
    assert capsys.readouterr().out == "Pack verified: 20 files match their hashes and the corpus.\n"


def test_cli_check_names_the_annotator_and_counts_the_expected_issues_without_writing(tmp_path, capsys):
    path = write(tmp_path / "base-commercial.annotation.json", filled())
    main(["check", str(path), "--corpus", str(CORPUS)])
    assert capsys.readouterr().out == "Annotation by Test Annotator A is valid: 2 expected issues.\n"
    assert files_in(tmp_path) == ["base-commercial.annotation.json"]


def test_cli_check_says_when_the_annotator_found_nothing_to_raise(tmp_path, capsys):
    path = write(tmp_path / "base-commercial.annotation.json", filled(issues=[]))
    main(["check", str(path), "--corpus", str(CORPUS)])
    assert capsys.readouterr().out == (
        "Annotation by Test Annotator A is valid: 0 expected issues (the annotator found nothing to raise).\n")


@pytest.mark.parametrize("command", ["check", "compile"])
@pytest.mark.parametrize("overrides, message", [
    *UNFILLED,
    ({"guidelineSha256": "0" * 64}, "made from a different pack"),
    ({"issues": [issue("COM-NOPE", 2)]}, "unknown playbook entry COM-NOPE"),
    ({"issues": [issue("COM-FEES", 13)]}, "paragraph 13 is outside the document"),
    ({"issues": [EXIT_MISSING, issue("COM-EXIT", 11)]}, "cannot be both missing and located"),
])
def test_cli_check_and_compile_refuse_what_the_readme_says_they_refuse(command, overrides, message, tmp_path):
    path = write(tmp_path / "base-commercial.annotation.json", filled(**overrides))
    with pytest.raises(ValueError, match=message):
        main([command, str(path), "--corpus", str(CORPUS), "--out", str(tmp_path / "reference.json")][
            :6 if command == "compile" else 4])
    assert files_in(tmp_path) == ["base-commercial.annotation.json"]


def test_cli_compile_prints_a_draft_that_names_the_hash_of_the_file_bytes(tmp_path, capsys):
    path = write(tmp_path / "base-commercial.annotation.json", filled())
    main(["compile", str(path), "--corpus", str(CORPUS)])
    reference = json.loads(capsys.readouterr().out)
    assert reference["status"] == "DRAFT"
    assert reference["reviewerEvidence"] == f"single annotation; annotation-sha256:{sha(path.read_bytes())}"
    assert reference == compile_reference(annotation(), CORPUS, annotation_sha256=sha(path.read_bytes()))


def test_cli_compile_writes_the_draft_and_replaces_an_older_reference(tmp_path, capsys):
    path = write(tmp_path / "base-commercial.annotation.json", filled())
    out = tmp_path / "base-commercial.draft.json"
    out.write_text("Test content of an older derived file", encoding="utf-8")
    main(["compile", str(path), "--corpus", str(CORPUS), "--out", str(out)])
    assert capsys.readouterr().out == (
        f"Wrote DRAFT reference to {out}. Independent review needs a second annotation and adjudication.\n")
    reference = CandidateReference.model_validate_json(out.read_text(encoding="utf-8"))
    assert reference.status == "DRAFT" and len(reference.issues) == 2


def test_cli_compile_refuses_to_overwrite_an_annotation_file(tmp_path):
    path = write(tmp_path / "base-commercial.annotation.json", filled())
    other = write(tmp_path / "other.annotation.json", filled(annotator="Test Annotator B"))
    for target in (path, other):
        before = target.read_bytes()
        with pytest.raises(FileExistsError, match="refusing to overwrite .*: it is an annotation"):
            main(["compile", str(path), "--corpus", str(CORPUS), "--out", str(target)])
        assert target.read_bytes() == before


@pytest.mark.xfail(strict=True, reason="SOURCE DEFECT: compile --out overwrites an adjudication record, "
                                       "which candidate_adjudication never replaces")
def test_cli_compile_refuses_to_overwrite_an_adjudication_record(tmp_path):
    path = write(tmp_path / "base-commercial.annotation.json", filled())
    record = tmp_path / "base-commercial.adjudication.json"
    record.write_text('{"schema": "mycounsel.candidate-adjudication.v1", "decisions": []}\n', encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        main(["compile", str(path), "--corpus", str(CORPUS), "--out", str(record)])
