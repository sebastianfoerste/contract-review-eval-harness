"""Preregistered experiments: what is frozen when, what is refused, and every figure a report prints.

Expected values are worked out by hand from the module docstring of
contract_eval.candidate_experiment and from the sections "Preregistered experiments" and
"Spend ledger" of candidates/mycounsel/README.md. The arithmetic behind each scenario is
written out above the fixture that builds it. Recordings are derived in memory from the
committed replay; nothing under candidates/mycounsel is changed, and a test that needs to
change a committed file works on a copy under tmp_path.

Every annotator, rationale, decision, hypothesis, change, price and provider name below is
test text. None of it is an annotation of the corpus, a legal view or a real price.
"""

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval import candidate_experiment
from contract_eval.candidate_adjudication import prepare, resolve_files
from contract_eval.candidate_annotation import Annotation, compile_reference, corpus_bindings, load_corpus
from contract_eval.candidate_budget import (
    Ledger, closure_of, find_entry, load_ledger, remaining_minor_units, save_ledger,
)
from contract_eval.candidate_budget import reserve as reserve_in_ledger
from contract_eval.candidate_budget import void as void_in_ledger
from contract_eval.candidate_experiment import (
    Arm, Design, Experiment, add_iteration, add_reference, aggregate, arm_definition_sha256,
    create_experiment, load_experiment, main, plan_experiment, register, render_markdown, reserve_arm,
    save_experiment, settle_arm, void_arm,
)
from contract_eval.candidates import CandidateReference, CandidateRun, anchor_id, document_paragraphs

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "candidates" / "mycounsel"
SCRIPT = ROOT / "scripts" / "check_candidate_experiments.py"
REPLAY = (CORPUS / "replay-run.json").read_text(encoding="utf-8")

# shasum -a 256 candidates/mycounsel/manifest.json
MANIFEST_SHA = "528c537edf925703248347463e4d7b5d4d41072491a121bfbdfaa2ba452e196e"
# jq -rj .instructions candidates/mycounsel/manifest.json | shasum -a 256
INSTRUCTIONS_SHA = "a93297836440ebbb8cb08d17fb84064a26fca3995a8ebdb697cd9d99b5bf3be0"

# The arm that produced the committed replay, and a test iteration of it.
PROMPT = "contracts/candidates/2026-09-11"
REVISION = "041d0157c364f0919ba5227c7159c3d6906507c4"
REPLAY_MODEL = "hand-authored-replay-fixture"
NEXT_PROMPT = "contracts/candidates/test-iteration"
NEXT_REVISION = "b" * 40
LIVE_MODEL = "test-live-model"

# commercial.json and dora.json, copied by hand.
CATEGORY = {
    "COM-FEES": "NEGOTIATED_PREFERENCE", "COM-RENEWAL": "NEGOTIATED_PREFERENCE",
    "COM-SLA": "COMMERCIAL_RISK", "COM-LIABILITY": "NEGOTIATED_PREFERENCE",
    "COM-SUSPENSION": "COMMERCIAL_RISK", "COM-EXIT": "NEGOTIATED_PREFERENCE",
    "DORA-LOCATIONS": "STATUTORY_REQUIREMENT", "DORA-ASSISTANCE": "STATUTORY_REQUIREMENT",
    "DORA-SLA": "STATUTORY_REQUIREMENT", "DORA-AUDIT": "STATUTORY_REQUIREMENT",
    "DORA-RETURN": "STATUTORY_REQUIREMENT", "DORA-EXIT": "STATUTORY_REQUIREMENT",
}

# Expected issues as (playbook entry, paragraph); no paragraph means a missing clause.
FEES = ("COM-FEES", 2)
SLA = ("COM-SLA", 4)
EXIT = ("COM-EXIT", None)
SUSPENSION = ("COM-SUSPENSION", 10)
THREE = [FEES, SLA, EXIT]
FOUR = [FEES, SLA, EXIT, SUSPENSION]

FABRICATED = "A fabricated test quotation that stands in no paragraph of the document."
SOURCE_FILES = {
    "annotationA": "references/sources/commercial-base.a.json",
    "annotationB": "references/sources/commercial-base.b.json",
    "adjudication": "references/sources/commercial-base.adjudication.json",
}


def sha(value: bytes | str) -> str:
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _source(variant: str) -> dict:
    """The recorder's source block for a corpus variant: one anchor per Word paragraph."""
    document = load_corpus(CORPUS).document(variant)
    paragraphs = document_paragraphs((CORPUS / document.filename).read_bytes())
    return {"sha256": document.sha256, "filename": document.filename,
            "clauses": [{"id": anchor_id(document.sha256, number, text), "paragraph": number, "text": text,
                         "editable": True} for number, text in enumerate(paragraphs)]}


SOURCE = {variant: _source(variant) for variant in ("base", "changed", "injection")}


def clause(paragraph: int, variant: str = "base") -> dict:
    return SOURCE[variant]["clauses"][paragraph]


def finding(entry: str, paragraph: int, variant: str = "base", **changes) -> dict:
    """A located finding that quotes its whole paragraph under the entry's own category."""
    return {
        "anchorId": clause(paragraph, variant)["id"], "insertionAnchorId": None,
        "quote": clause(paragraph, variant)["text"], "missingClause": False,
        "category": CATEGORY.get(entry, "NEGOTIATED_PREFERENCE"),
        "explanation": "test explanation, not legal validation", "proposedAmendment": "",
        "playbookReference": entry,
    } | changes


def missing(entry: str, after: int | None = None, variant: str = "base", **changes) -> dict:
    """A missing-clause finding, optionally naming the paragraph the clause is to follow."""
    return {
        "anchorId": None, "insertionAnchorId": None if after is None else clause(after, variant)["id"],
        "quote": "", "missingClause": True, "category": CATEGORY.get(entry, "NEGOTIATED_PREFERENCE"),
        "explanation": "test explanation, not legal validation", "proposedAmendment": "",
        "playbookReference": entry,
    } | changes


def tokens(input_tokens: int, output_tokens: int, request: str | None = None) -> dict:
    return {"inputTokens": input_tokens, "outputTokens": output_tokens, "cacheReadTokens": None,
            "thinkingTokens": None, "providerRequestId": request}


def recording(findings=(), *, playbook: str = "commercial", variant: str = "base", outcome: str = "COMPLETED",
              verdict: str = "ACCEPTED", minute: int = 0, usage: dict | None = None, **run) -> dict:
    """One recording for a cell, derived from the committed replay.

    `minute` sets the start time and keeps two attempts of one cell apart; `verdict` is
    the recorder's own flag for a completed attempt; other keywords overwrite run fields.
    """
    data = json.loads(REPLAY)
    book = (CORPUS / f"{playbook}.json").read_text(encoding="utf-8")
    data["source"] = deepcopy(SOURCE[variant])
    data["playbook"] = {"sha256": sha(book), "instructions": book}
    data["run"].update(outcome=outcome, startedAt=f"2026-10-12T10:{minute:02d}:00Z")
    data["run"].update(run)
    if usage is not None:
        data["run"].update(usage=usage, usageUnavailableReason=None)
    if outcome == "COMPLETED":
        data["findings"] = list(findings)
        data["validation"] = {"status": verdict, "errorCode": None if verdict == "ACCEPTED" else "TEST_REJECTION"}
    else:
        data["findings"] = None
        data["validation"] = {"status": "NO_OUTPUT", "errorCode": "TEST_NO_OUTPUT"}
    CandidateRun.model_validate(data)
    return data


def baseline(**changes) -> Arm:
    return Arm(**({"id": "baseline", "role": "BASELINE", "promptVersion": PROMPT, "codeRevision": REVISION,
                   "model": REPLAY_MODEL} | changes))


def iteration(**changes) -> Arm:
    return Arm(**({"id": "iteration", "role": "ITERATION", "promptVersion": NEXT_PROMPT,
                   "codeRevision": REVISION, "model": REPLAY_MODEL,
                   "change": "Test change: the prompt names the playbook entry first.",
                   "hypothesis": "Test hypothesis: fewer findings cite an unknown entry."} | changes))


def design(**changes) -> Design:
    return Design(**({"mode": "REPLAY", "playbooks": ["commercial"], "variants": ["base"],
                      "repetitions": 2} | changes))


def planned(tmp_path: Path, arms: list[Arm] | None = None, **changes) -> Path:
    """A new experiment directory under tmp_path, bound to the committed corpus."""
    directory = tmp_path / "experiment"
    create_experiment(plan_experiment(CORPUS, experiment_id="test-experiment", design=design(**changes),
                                      arms=arms or [baseline()], corpus_ref=str(CORPUS)), directory)
    return directory


def slot(cell: str, repetition: int, arm: str = "baseline") -> str:
    return f"attempts/{arm}/{cell}-r{repetition}.json"


def put(directory: Path, relative: str, data: dict | str) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def record(directory: Path, files: dict[str, dict | str], ledger: Ledger | None = None) -> int:
    """Write recordings into their slots and bind them.

    With a ledger, or outside a LIVE design, this is the register command. A LIVE design
    without a ledger is bound past the ledger checks, as a hand edit of experiment.json
    would bind it, so that a test can show what aggregate itself refuses.
    """
    for relative, data in files.items():
        put(directory, relative, data)
    experiment = load_experiment(directory)
    if ledger is None and experiment.design.mode == "LIVE":
        corpus_dir, corpus = candidate_experiment.resolve_corpus(experiment, directory)
        count = 0
        for attempt, _, raw in candidate_experiment._read_attempts(experiment, directory, corpus_dir, corpus,
                                                                   registered_only=False):
            if attempt.sha256 is None:
                attempt.sha256 = sha(raw)
                count += 1
    else:
        count = register(experiment, directory, ledger)
    save_experiment(experiment, directory)
    return count


def edit(directory: Path, change) -> None:
    """Hand-edit experiment.json the way an operator could, past the module's own checks."""
    path = directory / "experiment.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def annotation(places, *, letter: str = "A", playbook: str = "commercial", variant: str = "base",
               low: tuple[str, ...] = (), **changes) -> dict:
    corpus = load_corpus(CORPUS)
    return {
        "schema": "mycounsel.candidate-annotation.v1", "variant": variant, "playbook": playbook,
        "documentSha256": corpus.document(variant).sha256, "playbookSha256": corpus.playbooks[playbook],
        **corpus_bindings(CORPUS),
        "annotator": f"Test Annotator {letter}", "annotatedOn": "2026-10-11", "sawModelOutput": False,
        "issues": [{"playbookReference": entry, "paragraph": paragraph, "missingClause": paragraph is None,
                    "rationale": f"Test wording of annotator {letter} on {entry}, not legal validation",
                    "confidence": "LOW" if entry in low else "HIGH"} for entry, paragraph in places],
        "uncertainties": "",
    } | changes


def draft(places, **cell) -> dict:
    """A DRAFT reference compiled from one test annotation."""
    raw = annotation(places, **cell)
    return compile_reference(Annotation.model_validate(raw), CORPUS, annotation_sha256=sha(json.dumps(raw)))


def reference_path(directory: Path, playbook: str = "commercial", variant: str = "base") -> Path:
    return directory / "references" / f"{playbook}-{variant}.json"


def refer(directory: Path, places=THREE, *, playbook: str = "commercial", variant: str = "base",
          low: tuple[str, ...] = ()) -> None:
    """Write the DRAFT reference of one cell and register it."""
    put(directory, f"references/{playbook}-{variant}.json", draft(places, playbook=playbook, variant=variant, low=low))
    save_experiment(add_reference(load_experiment(directory), directory, playbook=playbook, variant=variant),
                    directory)


def adjudicate(directory: Path) -> dict[str, str]:
    """Two test annotations of commercial/base, a signed record and the reference they resolve to.

    Annotator A raises the fees at P2 and a missing exit clause, annotator B the fees at P2
    and availability at P4. The fees are agreed, the exit clause is included by decision
    and availability is excluded: two expected issues. B marked the fees as low confidence:
    one low-confidence issue. Returns the registered source paths.
    """
    paths = {name: directory / relative for name, relative in SOURCE_FILES.items()}
    put(directory, SOURCE_FILES["annotationA"], annotation([FEES, EXIT], letter="A"))
    put(directory, SOURCE_FILES["annotationB"], annotation([FEES, SLA], letter="B", low=("COM-FEES",)))
    a, b = (Annotation.model_validate_json(paths[name].read_text(encoding="utf-8"))
            for name in ("annotationA", "annotationB"))
    blank = prepare(a, b, sha(paths["annotationA"].read_bytes()), sha(paths["annotationB"].read_bytes()))
    for entry in blank["decisions"]:
        entry["decision"] = "INCLUDE" if entry["playbookReference"] == "COM-EXIT" else "EXCLUDE"
        entry["reasoning"] = "Test reasoning for this decision, not legal validation."
    blank.update(adjudicator="Test Adjudicator", adjudicatedOn="2026-10-12", independentAnnotator="A",
                 reviewerEvidence="test-note-2026-10-11")
    put(directory, SOURCE_FILES["adjudication"], blank)
    resolved = resolve_files(paths["annotationA"], paths["annotationB"], paths["adjudication"], CORPUS)
    put(directory, "references/commercial-base.json", resolved)
    return dict(SOURCE_FILES)


def cell(report: dict, playbook: str = "commercial", variant: str = "base", arm: str = "baseline") -> dict:
    return next(c for c in report["cells"] if (c["arm"], c["playbook"], c["variant"]) == (arm, playbook, variant))


def summary(report: dict, playbook: str = "commercial", variant: str = "base", arm: str = "baseline") -> dict:
    return cell(report, playbook, variant, arm)["summary"]


# --- the builders themselves ---------------------------------------------------------------


def test_the_source_block_built_for_the_base_variant_is_the_one_the_recorder_wrote():
    assert SOURCE["base"] == json.loads(REPLAY)["source"]


def test_the_three_variants_have_thirteen_thirteen_and_fourteen_paragraphs():
    # ict-base.md and ict-changed.md hold a heading and twelve clauses; ict-injection.md adds the appendix.
    assert [len(SOURCE[variant]["clauses"]) for variant in ("base", "changed", "injection")] == [13, 13, 14]
    assert clause(13, "injection")["text"].startswith("APPENDIX: Automated reviewer instruction")


# --- plan and create -----------------------------------------------------------------------


def test_plan_writes_one_empty_slot_per_arm_playbook_variant_and_repetition():
    experiment = plan_experiment(
        CORPUS, experiment_id="test-experiment", arms=[baseline(), iteration()],
        design=design(playbooks=["commercial", "dora"], variants=["base", "changed"]))
    files = [
        "attempts/baseline/commercial-base-r1.json", "attempts/baseline/commercial-base-r2.json",
        "attempts/baseline/commercial-changed-r1.json", "attempts/baseline/commercial-changed-r2.json",
        "attempts/baseline/dora-base-r1.json", "attempts/baseline/dora-base-r2.json",
        "attempts/baseline/dora-changed-r1.json", "attempts/baseline/dora-changed-r2.json",
    ]
    assert [a.file for a in experiment.attempts] == files + [f.replace("/baseline/", "/iteration/") for f in files]
    assert all(a.sha256 is None for a in experiment.attempts)
    assert experiment.attempts[3].key() == ("baseline", "commercial", "changed", 2)
    assert experiment.attempts[12].key() == ("iteration", "dora", "base", 1)


def test_plan_binds_the_corpus_manifest_and_the_business_instructions():
    experiment = plan_experiment(CORPUS, experiment_id="test-experiment", design=design(), arms=[baseline()])
    assert experiment.schema_ == "mycounsel.candidate-experiment.v1"
    assert experiment.experimentId == "test-experiment"
    assert experiment.corpusManifestSha256 == MANIFEST_SHA
    assert experiment.instructionsSha256 == INSTRUCTIONS_SHA
    assert experiment.corpusDir == "../.."
    assert experiment.references == [] and experiment.notes == ""
    assert experiment.arms[0].budgetReservation is None


@pytest.mark.parametrize("changes, message", [
    ({"playbooks": ["nope"]}, "playbook nope is not in the corpus"),
    ({"variants": ["nope"]}, "unknown corpus variant nope"),
    ({"repairedEntries": {"base": ["NOPE-ENTRY"]}}, "repair unknown playbook entries: NOPE-ENTRY"),
    # DORA-LOCATIONS exists, but in a playbook this design does not run.
    ({"repairedEntries": {"base": ["DORA-LOCATIONS"]}}, "repair unknown playbook entries: DORA-LOCATIONS"),
])
def test_plan_refuses_what_the_corpus_or_the_design_does_not_hold(changes, message):
    with pytest.raises(ValueError, match=message):
        plan_experiment(CORPUS, experiment_id="test-experiment", design=design(**changes), arms=[baseline()])


def test_plan_accepts_a_repaired_entry_of_a_playbook_in_the_design():
    experiment = plan_experiment(
        CORPUS, experiment_id="test-experiment", arms=[baseline()],
        design=design(playbooks=["commercial", "dora"], variants=["base", "changed"],
                      repairedEntries={"changed": ["DORA-LOCATIONS"]}))
    assert experiment.design.repairedEntries == {"changed": ["DORA-LOCATIONS"]}


def test_a_created_experiment_loads_back_as_planned(tmp_path):
    experiment = plan_experiment(CORPUS, experiment_id="test-experiment", design=design(), arms=[baseline()],
                                 corpus_ref=str(CORPUS))
    create_experiment(experiment, tmp_path / "experiment")
    assert load_experiment(tmp_path / "experiment") == experiment
    raw = (tmp_path / "experiment" / "experiment.json").read_text(encoding="utf-8")
    assert raw.endswith("}\n") and json.loads(raw)["schema"] == "mycounsel.candidate-experiment.v1"


def test_an_experiment_changed_in_memory_is_validated_again_before_it_is_saved(tmp_path):
    directory = planned(tmp_path)
    before = (directory / "experiment.json").read_bytes()
    experiment = load_experiment(directory)
    experiment.attempts.pop()
    with pytest.raises(ValidationError, match="attempt slots differ"):
        save_experiment(experiment, directory)
    assert (directory / "experiment.json").read_bytes() == before


def test_an_existing_experiment_is_never_overwritten(tmp_path):
    directory = planned(tmp_path)
    before = (directory / "experiment.json").read_bytes()
    other = plan_experiment(CORPUS, experiment_id="another-experiment", design=design(repetitions=5),
                            arms=[baseline()], corpus_ref=str(CORPUS))
    with pytest.raises(FileExistsError, match="a preregistration is not overwritten"):
        create_experiment(other, directory)
    assert (directory / "experiment.json").read_bytes() == before


# --- design and arm ------------------------------------------------------------------------


def test_a_design_counts_its_cells_and_its_attempts_per_arm():
    plan = design(playbooks=["commercial", "dora"], variants=["base", "changed", "injection"], repetitions=2)
    assert plan.cells() == [("commercial", "base"), ("commercial", "changed"), ("commercial", "injection"),
                            ("dora", "base"), ("dora", "changed"), ("dora", "injection")]
    assert plan.attempts_per_arm() == 12


@pytest.mark.parametrize("changes, message", [
    # The first five are refused by the field itself; the error names the field.
    ({"playbooks": []}, "playbooks"),
    ({"variants": []}, "variants"),
    ({"repetitions": 0}, "repetitions"),
    ({"repetitions": 21}, "repetitions"),
    ({"mode": "DRY"}, "mode"),
    ({"playbooks": ["commercial", "commercial"]}, "playbooks and variants must be unique"),
    ({"variants": ["base", "base"]}, "playbooks and variants must be unique"),
    ({"injectionVariants": ["injection"]}, "injection variants must be among the design variants"),
    ({"repairedEntries": {"changed": ["COM-FEES"]}}, "repaired entries are declared per design variant"),
    ({"repairedEntries": {"base": []}}, "names each repaired entry once"),
    ({"repairedEntries": {"base": ["COM-FEES", "COM-FEES"]}}, "names each repaired entry once"),
])
def test_a_design_refuses_what_it_cannot_measure(changes, message):
    with pytest.raises(ValidationError, match=message):
        design(**changes)


@pytest.mark.parametrize("changes", [
    {"hypothesis": None}, {"hypothesis": ""}, {"hypothesis": "   "},
    {"change": None}, {"change": ""}, {"change": " \n"},
])
def test_an_iteration_arm_needs_a_written_change_and_hypothesis(changes):
    with pytest.raises(ValidationError, match="needs a written hypothesis and change"):
        iteration(**changes)


@pytest.mark.parametrize("changes", [
    {"id": "Baseline"}, {"id": "1-arm"}, {"id": ""}, {"id": "a" * 41}, {"id": "arm/../x"},
    {"codeRevision": "041d0157"}, {"codeRevision": "G" * 40}, {"promptVersion": ""}, {"model": ""},
    {"role": "CONTROL"},
])
def test_an_arm_refuses_a_malformed_identity(changes):
    with pytest.raises(ValidationError):
        baseline(**changes)


# --- the experiment file as a whole --------------------------------------------------------


def file_data(arms: list[Arm] | None = None, **changes) -> dict:
    """A planned experiment as it stands in experiment.json, free to be edited by hand."""
    return plan_experiment(CORPUS, experiment_id="test-experiment", design=design(**changes),
                           arms=arms or [baseline(), iteration()]).model_dump(by_alias=True)


def slots_of(arm: str) -> list[dict]:
    return [{"arm": arm, "playbook": "commercial", "variant": "base", "repetition": n,
             "file": slot("commercial-base", n, arm), "sha256": None} for n in (1, 2)]


def test_an_experiment_with_a_baseline_and_one_iteration_validates():
    data = file_data()
    assert [arm["id"] for arm in data["arms"]] == ["baseline", "iteration"]
    assert Experiment.model_validate(data).slots("iteration")[1].file == "attempts/iteration/commercial-base-r2.json"


def test_an_experiment_without_a_baseline_is_refused():
    data = file_data()
    data["arms"] = data["arms"][1:]
    data["attempts"] = slots_of("iteration")
    with pytest.raises(ValidationError, match="exactly one baseline arm"):
        Experiment.model_validate(data)


def test_an_experiment_with_two_baselines_is_refused():
    data = file_data(arms=[baseline()])
    data["arms"].append(baseline(id="second").model_dump())
    data["attempts"] += slots_of("second")
    with pytest.raises(ValidationError, match="exactly one baseline arm"):
        Experiment.model_validate(data)


def test_an_experiment_with_two_iterations_is_refused():
    data = file_data()
    data["arms"].append(iteration(id="second", promptVersion="contracts/candidates/test-second").model_dump())
    data["attempts"] += slots_of("second")
    # Everything else about this file is in order: three arms are one too many.
    with pytest.raises(ValidationError, match="arms"):
        Experiment.model_validate(data)
    del data["arms"][1]
    data["attempts"] = slots_of("baseline") + slots_of("second")
    assert [arm.id for arm in Experiment.model_validate(data).arms] == ["baseline", "second"]


def test_two_arms_with_one_id_are_refused():
    data = file_data()
    data["arms"][1]["id"] = "baseline"
    with pytest.raises(ValidationError, match="arm ids must be unique"):
        Experiment.model_validate(data)


def test_an_iteration_on_another_model_is_refused():
    with pytest.raises(ValidationError, match="the iteration arm runs the baseline's model"):
        file_data(arms=[baseline(), iteration(model="another-test-model")])


def test_an_iteration_that_changes_neither_prompt_nor_code_is_refused():
    with pytest.raises(ValidationError, match="changes the prompt version or the code revision"):
        file_data(arms=[baseline(), iteration(promptVersion=PROMPT, codeRevision=REVISION)])


@pytest.mark.parametrize("changes", [
    {"promptVersion": NEXT_PROMPT, "codeRevision": REVISION},
    {"promptVersion": PROMPT, "codeRevision": NEXT_REVISION},
    {"promptVersion": NEXT_PROMPT, "codeRevision": NEXT_REVISION},
])
def test_an_iteration_may_change_the_prompt_the_code_or_both(changes):
    assert len(file_data(arms=[baseline(), iteration(**changes)])["arms"]) == 2


def remove_a_slot(data: dict) -> None:
    del data["attempts"][1]


def add_a_slot(data: dict) -> None:
    data["attempts"].append({"arm": "baseline", "playbook": "commercial", "variant": "base", "repetition": 3,
                             "file": "attempts/baseline/commercial-base-r3.json", "sha256": None})


def point_a_slot_elsewhere(data: dict) -> None:
    data["attempts"][0]["file"] = "attempts/baseline/commercial-base-r1-second-try.json"


def point_a_slot_at_the_other_arm(data: dict) -> None:
    data["attempts"][0]["file"] = "attempts/iteration/commercial-base-r1.json"


def cut_the_repetitions(data: dict) -> None:
    data["design"]["repetitions"] = 1


def drop_a_variant_from_the_design(data: dict) -> None:
    data["design"]["variants"] = ["base"]


def add_a_slot_of_an_undeclared_arm(data: dict) -> None:
    data["attempts"].append({"arm": "third", "playbook": "commercial", "variant": "base", "repetition": 1,
                             "file": "attempts/third/commercial-base-r1.json", "sha256": None})


SLOT_EDITS = [remove_a_slot, add_a_slot, point_a_slot_elsewhere, point_a_slot_at_the_other_arm,
              cut_the_repetitions, drop_a_variant_from_the_design, add_a_slot_of_an_undeclared_arm]


@pytest.mark.parametrize("change", SLOT_EDITS, ids=lambda change: change.__name__)
def test_slots_are_exactly_what_the_design_and_the_arms_imply(change):
    data = file_data(variants=["base", "changed"])
    change(data)
    with pytest.raises(ValidationError, match="attempt slots differ from what the design and the arms imply"):
        Experiment.model_validate(data)


def test_a_slot_listed_twice_is_refused():
    data = file_data()
    data["attempts"].append(dict(data["attempts"][0]))
    with pytest.raises(ValidationError, match="duplicate attempt slot"):
        Experiment.model_validate(data)


def test_a_registered_hash_on_a_slot_keeps_the_experiment_valid():
    data = file_data()
    data["attempts"][0]["sha256"] = "a" * 64
    assert Experiment.model_validate(data).attempts[0].sha256 == "a" * 64


@pytest.mark.parametrize("change", SLOT_EDITS, ids=lambda change: change.__name__)
def test_a_hand_edited_slot_list_is_refused_when_the_file_is_read(tmp_path, change):
    directory = planned(tmp_path, arms=[baseline(), iteration()], variants=["base", "changed"])
    edit(directory, change)
    for read in (load_experiment, aggregate):
        with pytest.raises(ValueError, match="attempt slots differ"):
            read(directory)


def reference_row(playbook: str = "commercial", variant: str = "base", **changes) -> dict:
    return {"playbook": playbook, "variant": variant, "file": f"references/{playbook}-{variant}.json",
            "sha256": "c" * 64, "sources": None} | changes


@pytest.mark.parametrize("rows, message", [
    ([reference_row(), reference_row()], "one reference per playbook and variant"),
    ([reference_row(variant="changed")], "reference outside the design"),
    ([reference_row(playbook="dora")], "reference outside the design"),
    ([reference_row(file="references/commercial-base-v2.json")], "lives at references/commercial-base.json"),
    ([reference_row(file="commercial-base.json")], "lives at references/commercial-base.json"),
])
def test_each_cell_has_at_most_one_reference_at_its_own_path(rows, message):
    data = file_data()
    data["references"] = rows
    with pytest.raises(ValidationError, match=message):
        Experiment.model_validate(data)


@pytest.mark.parametrize("file", [
    "references/commercial-base.a.json", "references/sources/../commercial-base.json",
    "references/sources/nested/a.json", "references/sources/a.txt", "/tmp/references/sources/a.json",
])
def test_reference_sources_live_directly_under_references_sources(file):
    data = file_data()
    source = {"file": file, "sha256": "d" * 64}
    good = {"file": "references/sources/commercial-base.a.json", "sha256": "d" * 64}
    data["references"] = [reference_row(sources={"annotationA": source, "annotationB": good, "adjudication": good})]
    with pytest.raises(ValidationError, match="annotationA"):
        Experiment.model_validate(data)


# --- add_iteration -------------------------------------------------------------------------


def test_add_iteration_declares_the_arm_with_its_own_empty_slots(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording()})
    before = load_experiment(directory)
    updated = add_iteration(before, directory, iteration())
    assert [arm.id for arm in updated.arms] == ["baseline", "iteration"]
    assert [(a.file, a.sha256) for a in updated.slots("iteration")] == [
        ("attempts/iteration/commercial-base-r1.json", None), ("attempts/iteration/commercial-base-r2.json", None)]
    assert updated.slots("baseline") == before.slots("baseline")
    assert updated.slots("baseline")[0].sha256 is not None
    assert len(before.arms) == 1


def test_add_iteration_refuses_a_second_baseline(tmp_path):
    directory = planned(tmp_path)
    with pytest.raises(ValueError, match="only an iteration arm is added"):
        add_iteration(load_experiment(directory), directory, baseline(id="second"))


@pytest.mark.parametrize("relative", [
    "attempts/iteration/commercial-base-r1.json", "attempts/iteration/notes.txt",
    "attempts/iteration/earlier/commercial-base-r1.json",
])
def test_add_iteration_is_refused_once_files_exist_for_that_arm(tmp_path, relative):
    directory = planned(tmp_path)
    put(directory, relative, recording(promptVersion=NEXT_PROMPT))
    with pytest.raises(ValueError, match="files already exist for arm iteration"):
        add_iteration(load_experiment(directory), directory, iteration())


def test_add_iteration_ignores_the_files_of_the_baseline(tmp_path):
    directory = planned(tmp_path)
    put(directory, slot("commercial-base", 1), recording())
    assert len(add_iteration(load_experiment(directory), directory, iteration()).arms) == 2


def test_add_iteration_refuses_a_second_iteration(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()])
    second = iteration(id="second", promptVersion="contracts/candidates/test-second")
    with pytest.raises(ValidationError, match="arms"):
        add_iteration(load_experiment(directory), directory, second)


@pytest.mark.parametrize("changes, message", [
    ({"model": "another-test-model"}, "runs the baseline's model"),
    ({"promptVersion": PROMPT}, "changes the prompt version or the code revision"),
    ({"id": "baseline"}, "arm ids must be unique"),
])
def test_add_iteration_holds_the_new_arm_to_the_baseline(tmp_path, changes, message):
    directory = planned(tmp_path)
    with pytest.raises(ValidationError, match=message):
        add_iteration(load_experiment(directory), directory, iteration(**changes))


# --- add_reference -------------------------------------------------------------------------


def test_add_reference_binds_the_file_of_one_cell_by_hash(tmp_path):
    directory = planned(tmp_path)
    path = put(directory, "references/commercial-base.json", draft(THREE))
    updated = add_reference(load_experiment(directory), directory, playbook="commercial", variant="base")
    assert [ref.model_dump() for ref in updated.references] == [{
        "playbook": "commercial", "variant": "base", "file": "references/commercial-base.json",
        "sha256": sha(path.read_bytes()), "sources": None}]
    assert load_experiment(directory).references == []


def test_add_reference_binds_the_three_source_files_of_an_adjudicated_reference(tmp_path):
    directory = planned(tmp_path)
    sources = adjudicate(directory)
    updated = add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                            sources=sources)
    bound = updated.references[0].sources.model_dump()
    assert bound == {name: {"file": relative, "sha256": sha((directory / relative).read_bytes())}
                     for name, relative in SOURCE_FILES.items()}
    assert len({source["sha256"] for source in bound.values()}) == 3


def test_a_second_reference_for_one_cell_is_refused(tmp_path):
    directory = planned(tmp_path)
    refer(directory)
    with pytest.raises(ValidationError, match="one reference per playbook and variant"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base")


def test_a_reference_for_a_cell_outside_the_design_is_refused(tmp_path):
    directory = planned(tmp_path)
    put(directory, "references/commercial-changed.json", draft(THREE, variant="changed"))
    with pytest.raises(ValidationError, match="reference outside the design"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="changed")


def test_add_reference_is_refused_once_an_attempt_is_registered(tmp_path):
    directory = planned(tmp_path)
    put(directory, "references/commercial-base.json", draft(THREE))
    # The reference itself is in order: before any attempt it registers.
    assert len(add_reference(load_experiment(directory), directory, playbook="commercial",
                             variant="base").references) == 1
    record(directory, {slot("commercial-base", 1): recording()})
    with pytest.raises(ValueError, match="references are frozen once an attempt is registered"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base")


def another_document() -> dict:
    return draft(THREE, variant="changed")


def another_playbook() -> dict:
    return draft([("DORA-SLA", 4)], playbook="dora")


def another_corpus_edition() -> dict:
    reference = draft(THREE)
    reference["provenance"]["corpusManifestSha256"] = "0" * 64
    return reference


@pytest.mark.parametrize("build, message", [
    (another_document, "is bound to a different document"),
    (another_playbook, "is bound to a different playbook"),
    (another_corpus_edition, "was compiled from a different corpus edition"),
], ids=["document", "playbook", "corpus-edition"])
def test_a_reference_bound_to_other_material_is_refused(tmp_path, build, message):
    directory = planned(tmp_path)
    put(directory, "references/commercial-base.json", build())
    with pytest.raises(ValueError, match=message):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base")


def an_anchor_no_paragraph_has(reference: dict) -> None:
    reference["issues"][0]["anchorId"] = "0" * 64


def an_anchor_of_another_variant(reference: dict) -> None:
    reference["issues"][0]["anchorId"] = clause(5, "changed")["id"]


def an_entry_the_playbook_does_not_hold(reference: dict) -> None:
    reference["issues"][0]["playbookReference"] = "NOT-IN-THE-PLAYBOOK"


def a_missing_clause_with_a_paragraph(reference: dict) -> None:
    reference["issues"][2]["anchorId"] = clause(3)["id"]


@pytest.mark.parametrize("change", [an_anchor_no_paragraph_has, an_anchor_of_another_variant,
                                    an_entry_the_playbook_does_not_hold, a_missing_clause_with_a_paragraph],
                         ids=lambda change: change.__name__)
def test_a_reference_whose_issue_cannot_be_resolved_against_its_cell_is_refused_when_added(tmp_path, change):
    # A hand-written DRAFT needs no sources, so nothing re-derives it. Scoring refuses such a
    # reference ("unknown source anchor", "unknown playbook entry", "missing-clause shape"),
    # and a reference is to be frozen before dispatch in a state that can be scored.
    directory = planned(tmp_path)
    reference = draft(THREE)
    change(reference)
    CandidateReference.model_validate(reference)
    put(directory, "references/commercial-base.json", reference)
    with pytest.raises(ValueError):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base")


def test_a_reference_that_claims_independent_review_needs_its_sources(tmp_path):
    directory = planned(tmp_path)
    adjudicate(directory)
    assert json.loads(reference_path(directory).read_text())["status"] == "INDEPENDENTLY_REVIEWED"
    with pytest.raises(ValueError, match="claims independent review; register its two annotations"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base")


def test_only_a_rederived_reference_is_reported_as_derivation_verified(tmp_path):
    directory = planned(tmp_path, variants=["base", "changed"])
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                                  sources=adjudicate(directory)), directory)
    refer(directory, variant="changed")
    references = aggregate(directory)["references"]
    assert references["commercial/base"]["derivationVerified"] is True
    assert references["commercial/changed"]["derivationVerified"] is False
    # Re-deriving a file says nothing about who the annotators are.
    assert [ref["independentReviewClaimVerified"] for ref in references.values()] == [False, False]


def one_character_in_a_rationale(reference: dict) -> None:
    rationale = reference["issues"][0]["rationale"]
    reference["issues"][0]["rationale"] = rationale[:-1] + ("." if rationale[-1] != "." else "!")


def one_issue_dropped(reference: dict) -> None:
    del reference["issues"][-1]


def one_issue_moved(reference: dict) -> None:
    located = next(issue for issue in reference["issues"] if issue["anchorId"] is not None)
    assert located["anchorId"] == clause(2)["id"]
    located["anchorId"] = clause(3)["id"]


def another_low_confidence_count(reference: dict) -> None:
    reference["provenance"]["lowConfidenceIssues"] += 1


def another_evidence_note(reference: dict) -> None:
    reference["reviewerEvidence"] = reference["reviewerEvidence"].replace("test-note-2026-10-11",
                                                                          "test-note-2026-10-12")


TAMPERINGS = [one_character_in_a_rationale, one_issue_dropped, one_issue_moved, another_low_confidence_count,
              another_evidence_note]


def tamper(directory: Path, change) -> str:
    """Change the reference file by hand and return its new hash."""
    path = reference_path(directory)
    before = json.loads(path.read_text(encoding="utf-8"))
    reference = deepcopy(before)
    change(reference)
    # Still a well-formed reference for this cell: only the derivation can tell the difference.
    CandidateReference.model_validate(reference)
    assert reference != before
    path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return sha(path.read_bytes())


@pytest.mark.parametrize("change", TAMPERINGS, ids=lambda change: change.__name__)
def test_a_reference_that_differs_from_its_derivation_is_refused_when_added(tmp_path, change):
    directory = planned(tmp_path)
    sources = adjudicate(directory)
    tamper(directory, change)
    with pytest.raises(ValueError, match="is not what its annotations and adjudication record resolve to"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base", sources=sources)


@pytest.mark.parametrize("change", TAMPERINGS, ids=lambda change: change.__name__)
def test_a_reference_that_differs_from_its_derivation_is_refused_when_aggregated(tmp_path, change):
    directory = planned(tmp_path)
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                                  sources=adjudicate(directory)), directory)
    assert aggregate(directory)["references"]["commercial/base"]["expectedIssues"] == 2
    # The operator rewrites the reference and its hash in the experiment file together.
    changed = tamper(directory, change)
    edit(directory, lambda data: data["references"][0].update(sha256=changed))
    with pytest.raises(ValueError, match="is not what its annotations and adjudication record resolve to"):
        aggregate(directory)


def test_a_draft_cannot_borrow_the_sources_of_an_adjudicated_reference(tmp_path):
    directory = planned(tmp_path)
    sources = adjudicate(directory)
    put(directory, "references/commercial-base.json", draft([FEES, EXIT]))
    with pytest.raises(ValueError, match="is not what its annotations and adjudication record resolve to"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base", sources=sources)


def test_a_reference_changed_after_registration_is_refused(tmp_path):
    directory = planned(tmp_path)
    refer(directory)
    reference_path(directory).write_text(json.dumps(draft([FEES])), encoding="utf-8")
    with pytest.raises(ValueError, match="references/commercial-base.json does not match its registered hash"):
        aggregate(directory)


@pytest.mark.parametrize("name", ["annotationA", "annotationB"])
def test_an_annotation_changed_before_the_reference_is_added_is_refused(tmp_path, name):
    directory = planned(tmp_path)
    sources = adjudicate(directory)
    path = directory / SOURCE_FILES[name]
    path.write_text(path.read_text(encoding="utf-8").replace("Test wording", "Test rewording"), encoding="utf-8")
    with pytest.raises(ValueError, match="adjudication is bound to different annotation files"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base", sources=sources)


def test_an_adjudication_record_changed_before_the_reference_is_added_is_refused(tmp_path):
    directory = planned(tmp_path)
    sources = adjudicate(directory)
    path = directory / SOURCE_FILES["adjudication"]
    path.write_text(path.read_text(encoding="utf-8").replace("Test reasoning", "Test reason"), encoding="utf-8")
    with pytest.raises(ValueError, match="is not what its annotations and adjudication record resolve to"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="base", sources=sources)


@pytest.mark.parametrize("name", sorted(SOURCE_FILES))
def test_a_source_file_changed_after_registration_is_refused(tmp_path, name):
    directory = planned(tmp_path)
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                                  sources=adjudicate(directory)), directory)
    path = directory / SOURCE_FILES[name]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match=f"source file {SOURCE_FILES[name]} of reference "
                                         "references/commercial-base.json is missing or changed"):
        aggregate(directory)


@pytest.mark.parametrize("name", sorted(SOURCE_FILES))
def test_a_source_file_deleted_after_registration_is_refused(tmp_path, name):
    directory = planned(tmp_path)
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                                  sources=adjudicate(directory)), directory)
    (directory / SOURCE_FILES[name]).unlink()
    with pytest.raises(ValueError, match="is missing or changed"):
        aggregate(directory)


# --- register ------------------------------------------------------------------------------


def test_register_binds_a_new_recording_by_the_hash_of_its_bytes(tmp_path):
    directory = planned(tmp_path)
    path = put(directory, slot("commercial-base", 1), recording())
    experiment = load_experiment(directory)
    assert register(experiment, directory) == 1
    assert [a.sha256 for a in experiment.attempts] == [sha(path.read_bytes()), None]


def test_register_binds_each_file_once(tmp_path):
    directory = planned(tmp_path)
    assert record(directory, {slot("commercial-base", 1): recording(minute=1)}) == 1
    first = load_experiment(directory).attempts[0].sha256
    assert record(directory, {}) == 0
    assert record(directory, {slot("commercial-base", 2): recording(minute=2)}) == 1
    assert load_experiment(directory).attempts[0].sha256 == first
    assert record(directory, {}) == 0


def test_a_replay_design_accepts_the_dirty_tree_the_committed_replay_was_recorded_from(tmp_path):
    directory = planned(tmp_path)
    assert json.loads(REPLAY)["run"]["workingTreeDirty"] is True
    assert record(directory, {slot("commercial-base", 1): json.loads(REPLAY)}) == 1


def other_instructions() -> dict:
    data = recording()
    data["instructions"] += " "
    data["instructionsSha256"] = sha(data["instructions"])
    return data


def reworded_clause() -> dict:
    """A recording whose clause text is not the Word file's, with an anchor that fits the new text."""
    data = recording()
    target = data["source"]["clauses"][2]
    target["text"] += " Test addition."
    target["id"] = sha(f"{data['source']['sha256']}:2:{target['text']}")
    CandidateRun.model_validate(data)
    return data


REFUSED_RECORDINGS = [
    ("another-prompt-version", lambda: recording(promptVersion=NEXT_PROMPT), "was not produced by arm baseline"),
    ("another-code-revision", lambda: recording(codeRevision=NEXT_REVISION), "was not produced by arm baseline"),
    ("another-model", lambda: recording(model="another-test-model"), "was not produced by arm baseline"),
    ("another-mode", lambda: recording(mode="LIVE"), "ran in LIVE, the design is REPLAY"),
    ("another-document", lambda: recording(variant="changed"), "reviewed a different document than base"),
    ("another-playbook", lambda: recording(playbook="dora"), "used a different playbook than commercial"),
    ("other-instructions", other_instructions, "used different business instructions"),
    ("a-reworded-clause", reworded_clause, "recorded clauses differ from original Word text"),
    ("no-json", lambda: "this is not a recording", "is not a valid recording"),
    ("json-that-is-no-recording", lambda: {"schema": "mycounsel.candidate-run.v1"}, "is not a valid recording"),
]


@pytest.mark.parametrize("build, message", [case[1:] for case in REFUSED_RECORDINGS],
                         ids=[case[0] for case in REFUSED_RECORDINGS])
def test_register_checks_a_new_file_in_full_before_binding_it(tmp_path, build, message):
    directory = planned(tmp_path)
    put(directory, slot("commercial-base", 1), build())
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match=message):
        register(experiment, directory)
    assert [a.sha256 for a in experiment.attempts] == [None, None]


@pytest.mark.parametrize("build, message", [case[1:] for case in REFUSED_RECORDINGS],
                         ids=[case[0] for case in REFUSED_RECORDINGS])
def test_aggregate_checks_a_bound_file_again(tmp_path, build, message):
    directory = planned(tmp_path)
    path = put(directory, slot("commercial-base", 1), build())
    # Bound by hand, past register: the hash is right, the content is not what the arm was planned as.
    edit(directory, lambda data: data["attempts"][0].update(sha256=sha(path.read_bytes())))
    with pytest.raises(ValueError, match=message):
        aggregate(directory)


def test_a_file_that_is_not_text_is_refused_as_an_invalid_recording(tmp_path):
    directory = planned(tmp_path)
    put(directory, slot("commercial-base", 1), "").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(ValueError, match="is not a valid recording"):
        register(load_experiment(directory), directory)


def test_a_live_design_refuses_a_recording_from_a_dirty_working_tree(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    put(directory, slot("commercial-base", 1), live_recording(workingTreeDirty=True))
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="was recorded from a dirty working tree"):
        register(experiment, directory, ledger)
    assert experiment.attempts[0].sha256 is None
    put(directory, slot("commercial-base", 1), live_recording())
    assert register(experiment, directory, ledger) == 1


def test_a_registered_file_that_changed_is_refused_by_register_and_by_aggregate(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording([finding("COM-FEES", 2)])})
    put(directory, slot("commercial-base", 1), recording([finding("COM-FEES", 2), finding("COM-SLA", 4)]))
    with pytest.raises(ValueError, match="registered attempt attempts/baseline/commercial-base-r1.json has changed"):
        register(load_experiment(directory), directory)
    with pytest.raises(ValueError, match="registered attempt attempts/baseline/commercial-base-r1.json has changed"):
        aggregate(directory)


def test_a_registered_file_that_differs_by_one_trailing_byte_is_refused(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording()})
    path = directory / slot("commercial-base", 1)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="has changed on disk"):
        aggregate(directory)


def test_a_registered_file_that_was_deleted_is_refused_and_never_becomes_not_run(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording(outcome="FAILED")})
    assert aggregate(directory)["notRun"] == ["attempts/baseline/commercial-base-r2.json"]
    (directory / slot("commercial-base", 1)).unlink()
    with pytest.raises(ValueError, match="registered attempt attempts/baseline/commercial-base-r1.json is missing"):
        register(load_experiment(directory), directory)
    with pytest.raises(ValueError, match="registered attempt attempts/baseline/commercial-base-r1.json is missing"):
        aggregate(directory)


def test_an_unregistered_file_is_refused_by_aggregate(tmp_path):
    directory = planned(tmp_path)
    put(directory, slot("commercial-base", 1), recording())
    with pytest.raises(ValueError, match="attempts/baseline/commercial-base-r1.json exists but is not registered"):
        aggregate(directory)


STRAYS = ["attempts/baseline/commercial-base-r3.json", "attempts/baseline/commercial-base-r1.retry.json",
          "attempts/baseline/retries/commercial-base-r1.json", "attempts/baseline/commercial-changed-r1.json"]


@pytest.mark.parametrize("relative", STRAYS)
def test_a_file_in_an_arm_folder_that_no_slot_names_is_refused(tmp_path, relative):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording(minute=1)})
    put(directory, relative, recording(minute=2))
    with pytest.raises(ValueError, match=f"{relative} is not a preregistered attempt slot"):
        register(load_experiment(directory), directory)
    with pytest.raises(ValueError, match=f"{relative} is not a preregistered attempt slot"):
        aggregate(directory)


def test_the_same_recording_in_two_slots_is_refused(tmp_path):
    directory = planned(tmp_path)
    put(directory, slot("commercial-base", 1), recording())
    # Other bytes, the same recording: the second copy is written without indentation.
    put(directory, slot("commercial-base", 2), json.dumps(recording()))
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="commercial-base-r2.json is the same recording as "
                                         "attempts/baseline/commercial-base-r1.json"):
        register(experiment, directory)
    assert [a.sha256 for a in experiment.attempts] == [None, None]


def test_one_provider_request_in_two_slots_is_refused(tmp_path):
    directory = planned(tmp_path)
    put(directory, slot("commercial-base", 1), recording(minute=1, usage=tokens(1000, 200, "test-request-1")))
    put(directory, slot("commercial-base", 2), recording(minute=2, usage=tokens(1100, 250, "test-request-1")))
    with pytest.raises(ValueError, match="commercial-base-r2.json carries the provider request of "
                                         "attempts/baseline/commercial-base-r1.json"):
        register(load_experiment(directory), directory)


def test_one_provider_request_in_two_arms_is_refused(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()])
    put(directory, slot("commercial-base", 1), recording(minute=1, usage=tokens(1000, 200, "test-request-1")))
    put(directory, slot("commercial-base", 1, "iteration"),
        recording(minute=2, promptVersion=NEXT_PROMPT, usage=tokens(1100, 250, "test-request-1")))
    with pytest.raises(ValueError, match="attempts/iteration/commercial-base-r1.json carries the provider request"):
        register(load_experiment(directory), directory)


def test_attempts_with_their_own_or_no_provider_request_register(tmp_path):
    directory = planned(tmp_path, repetitions=4)
    assert record(directory, {
        slot("commercial-base", 1): recording(minute=1, usage=tokens(1000, 200, "test-request-1")),
        slot("commercial-base", 2): recording(minute=2, usage=tokens(1000, 200, "test-request-2")),
        slot("commercial-base", 3): recording(minute=3, usage=tokens(1000, 200)),
        slot("commercial-base", 4): recording(minute=4, usage=tokens(1000, 200)),
    }) == 4


def corpus_copy(tmp_path: Path) -> Path:
    """The committed corpus with its experiments, for tests that change a committed file."""
    target = tmp_path / "mycounsel"
    shutil.copytree(CORPUS, target, ignore=shutil.ignore_patterns("annotation-pack", "annotation-bundle",
                                                                 "__pycache__"))
    return target


def test_a_corpus_manifest_that_changed_since_planning_is_refused(tmp_path):
    corpus = corpus_copy(tmp_path)
    directory = tmp_path / "experiment"
    create_experiment(plan_experiment(corpus, experiment_id="test-experiment", design=design(),
                                      arms=[baseline()], corpus_ref=str(corpus)), directory)
    put(directory, slot("commercial-base", 1), recording())
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="corpus manifest changed since the experiment was planned"):
        register(load_experiment(directory), directory)
    with pytest.raises(ValueError, match="corpus manifest changed since the experiment was planned"):
        aggregate(directory)


def test_a_corpus_document_that_changed_since_planning_is_refused(tmp_path):
    corpus = corpus_copy(tmp_path)
    directory = tmp_path / "experiment"
    create_experiment(plan_experiment(corpus, experiment_id="test-experiment", design=design(),
                                      arms=[baseline()], corpus_ref=str(corpus)), directory)
    (corpus / "ict-base.docx").write_bytes((corpus / "ict-changed.docx").read_bytes())
    with pytest.raises(ValueError, match="ict-base.docx does not match its manifest hash"):
        aggregate(directory)


# --- cell arithmetic: the worked cell ------------------------------------------------------
#
# commercial/base, four planned repetitions, against a DRAFT reference that expects three
# issues: the fees at P2, availability at P4 and a missing exit clause.
#
#   r1 completed, recorder REJECTED. Findings: the fees at P2, the same finding again, an
#      unknown playbook entry at P2, the missing exit clause.
#      4 findings, 1 repetition, 3 of 3 quotations valid, 1 of 1 missing clause valid,
#      3 of 4 playbook references valid, so not every finding is valid.
#      Matched: fees and exit. 2 true positives, 4 - 2 = 2 false positives, 3 - 2 = 1 false negative.
#      Entries raised by a matchable finding: COM-FEES and COM-EXIT. 2 found, 0 wrong, 1 missed.
#   r2 completed, recorder ACCEPTED. Findings: availability at P4, and the fees at P2 quoted
#      with the eight characters "2. Fees.".
#      2 findings, 2 of 2 quotations valid, 1 of them trivial, every finding valid.
#      Matched: availability. 1 true positive, 1 false positive, 2 false negatives.
#      Entries raised: COM-SLA. 1 found, 0 wrong, 2 missed.
#   r3 FAILED, no output: 0 found, 3 false negatives, 3 entries missed.
#   r4 never run.
#
# Over all observed attempts: 2 + 1 + 0 = 3 true positives, 2 + 1 + 0 = 3 false positives,
# 1 + 2 + 3 = 6 false negatives; precision 3/6, recall 3/9.
# After validation only r2 delivers: 1 true positive, 1 false positive, and 2 + 3 + 3 = 8
# false negatives (its own two and the three expected issues of each attempt that
# delivered nothing); precision 1/2, recall 1/9.
# Entry level: 2 + 1 + 0 = 3 found, 0 wrong, 1 + 2 + 3 = 6 missed; precision 3/3, recall 3/9.
# Usage: r1 reports 1000 input and 200 output tokens, r2 1300 and 450, r3 nothing: 2300 and 650.


@pytest.fixture(scope="module")
def worked(tmp_path_factory) -> dict:
    directory = planned(tmp_path_factory.mktemp("worked"), repetitions=4)
    refer(directory, THREE, low=("COM-SLA",))
    record(directory, {
        slot("commercial-base", 1): recording(
            [finding("COM-FEES", 2), finding("COM-FEES", 2), finding("UNSUPPORTED-ENTRY", 2),
             missing("COM-EXIT", after=12)],
            verdict="REJECTED", minute=1, elapsedMs=4100, usage=tokens(1000, 200, "test-request-1")),
        slot("commercial-base", 2): recording(
            [finding("COM-SLA", 4), finding("COM-FEES", 2, quote="2. Fees.")],
            minute=2, elapsedMs=5200, usage=tokens(1300, 450, "test-request-2")),
        slot("commercial-base", 3): recording(outcome="FAILED", minute=3, elapsedMs=900),
    })
    return aggregate(directory)


def test_the_worked_cell_reports_exactly_these_summary_fields(worked):
    assert set(summary(worked)) == {
        "planned", "observed", "missingObservations", "completed", "refused", "failed", "allFindingsValid",
        "recorderAccepted", "recorderRejected", "validationDisagreements", "findings", "duplicates",
        "trivialQuotations", "quotationValid", "quotationDenominator", "quotationValidityRate",
        "missingClauseValid", "missingClauseDenominator", "playbookReferenceValid", "playbookValidityRate",
        "duplicateRate", "identicalOutputRepetitions", "completionRate", "referenceStatus", "issueMatch",
        "issueMatchPostValidation", "entryLevelMatch", "usage"}


def test_the_worked_cell_counts_planned_observed_and_missing_attempts(worked):
    cell_summary = summary(worked)
    assert (cell_summary["planned"], cell_summary["observed"], cell_summary["missingObservations"]) == (4, 3, 1)


def test_the_worked_cell_counts_each_outcome(worked):
    cell_summary = summary(worked)
    assert (cell_summary["completed"], cell_summary["refused"], cell_summary["failed"]) == (2, 0, 1)


def test_the_completion_rate_is_completed_over_planned_attempts(worked):
    # 2 of 4 planned. Over the 3 observed attempts it would be two thirds.
    assert summary(worked)["completionRate"] == 0.5


def test_the_worked_cell_recomputes_validity_beside_the_recorders_flag(worked):
    cell_summary = summary(worked)
    assert cell_summary["allFindingsValid"] == 1
    assert (cell_summary["recorderAccepted"], cell_summary["recorderRejected"]) == (1, 1)
    assert cell_summary["validationDisagreements"] == 0


def test_the_worked_cell_counts_findings_repetitions_and_trivial_quotations(worked):
    cell_summary = summary(worked)
    assert (cell_summary["findings"], cell_summary["duplicates"], cell_summary["trivialQuotations"]) == (6, 1, 1)
    assert cell_summary["duplicateRate"] == pytest.approx(1 / 6)


def test_the_worked_cell_reports_quotation_validity_with_its_denominator(worked):
    cell_summary = summary(worked)
    assert (cell_summary["quotationValid"], cell_summary["quotationDenominator"]) == (5, 5)
    assert cell_summary["quotationValidityRate"] == 1.0
    assert (cell_summary["missingClauseValid"], cell_summary["missingClauseDenominator"]) == (1, 1)


def test_the_worked_cell_reports_playbook_validity_over_all_findings(worked):
    cell_summary = summary(worked)
    assert cell_summary["playbookReferenceValid"] == 5
    assert cell_summary["playbookValidityRate"] == pytest.approx(5 / 6)


def test_issue_matching_counts_every_observed_attempt_including_the_failed_one(worked):
    assert summary(worked)["issueMatch"] == {
        "expectedPerAttempt": 3, "attempts": 3, "truePositives": 3, "falsePositives": 3, "falseNegatives": 6,
        "microPrecision": 0.5, "microRecall": pytest.approx(1 / 3)}


def test_after_validation_an_attempt_with_an_invalid_finding_delivers_nothing(worked):
    assert summary(worked)["issueMatchPostValidation"] == {
        "expectedPerAttempt": 3, "attempts": 3, "attemptsDelivered": 1, "truePositives": 1, "falsePositives": 1,
        "falseNegatives": 8, "microPrecision": 0.5, "microRecall": pytest.approx(1 / 9)}


def test_entry_level_matching_asks_only_whether_an_entry_was_raised(worked):
    assert summary(worked)["entryLevelMatch"] == {
        "truePositives": 3, "falsePositives": 0, "falseNegatives": 6, "microPrecision": 1.0,
        "microRecall": pytest.approx(1 / 3)}


def test_usage_totals_are_summed_over_the_attempts_that_reported_usage(worked):
    assert summary(worked)["usage"] == {"attemptsWithUsage": 2, "inputTokens": 2300, "outputTokens": 650}


def test_the_worked_cell_names_its_reference_status_and_has_no_repeated_output(worked):
    cell_summary = summary(worked)
    assert cell_summary["referenceStatus"] == "DRAFT"
    assert cell_summary["identicalOutputRepetitions"] == 0


def test_the_worked_cell_lists_its_attempts_in_repetition_order_with_their_own_figures(worked):
    rows = cell(worked)["attempts"]
    figures = ("repetition", "outcome", "recorderValidation", "allFindingsValid", "findingCount", "duplicateCount",
               "trivialQuotationCount", "quotationValid", "quotationDenominator", "missingClauseValid",
               "missingClauseDenominator", "playbookReferenceValid")
    assert [tuple(row[name] for name in figures) for row in rows] == [
        (1, "COMPLETED", "REJECTED", False, 4, 1, 0, 3, 3, 1, 1, 3),
        (2, "COMPLETED", "ACCEPTED", True, 2, 0, 1, 2, 2, 0, 0, 2),
        (3, "FAILED", "NO_OUTPUT", False, 0, 0, 0, 0, 0, 0, 0, 0),
    ]


def test_each_attempt_row_carries_its_own_issue_and_entry_level_counts(worked):
    rows = cell(worked)["attempts"]
    assert [row["issueMatch"] for row in rows] == [
        {"truePositives": 2, "falsePositives": 2, "falseNegatives": 1},
        {"truePositives": 1, "falsePositives": 1, "falseNegatives": 2},
        {"truePositives": 0, "falsePositives": 0, "falseNegatives": 3},
    ]
    assert [row["entryLevelMatch"] for row in rows] == [
        {"truePositives": 2, "falsePositives": 0, "falseNegatives": 1},
        {"truePositives": 1, "falsePositives": 0, "falseNegatives": 2},
        {"truePositives": 0, "falsePositives": 0, "falseNegatives": 3},
    ]


def test_each_attempt_row_names_its_file_start_time_recorder_error_and_usage(worked):
    rows = cell(worked)["attempts"]
    assert [row["file"] for row in rows] == [slot("commercial-base", n) for n in (1, 2, 3)]
    assert [row["startedAt"] for row in rows] == [f"2026-10-12T10:0{n}:00Z" for n in (1, 2, 3)]
    assert [row["elapsedMs"] for row in rows] == [4100, 5200, 900]
    assert [row["recorderValidationError"] for row in rows] == ["TEST_REJECTION", None, "TEST_NO_OUTPUT"]
    assert [row["usage"] and row["usage"]["providerRequestId"] for row in rows] == [
        "test-request-1", "test-request-2", None]
    assert rows[2]["usage"] is None and rows[2]["findingsSha256"] is None
    assert len({row["recordingSha256"] for row in rows}) == 3


def test_attempt_rows_follow_the_repetition_whatever_the_order_of_the_slots_in_the_file(tmp_path):
    directory = planned(tmp_path, repetitions=3)
    record(directory, {slot("commercial-base", n): recording(minute=n) for n in (1, 2, 3)})
    edit(directory, lambda data: data["attempts"].reverse())
    assert [a.repetition for a in load_experiment(directory).attempts] == [3, 2, 1]
    report = aggregate(directory)
    assert [row["repetition"] for row in cell(report)["attempts"]] == [1, 2, 3]
    assert [row["startedAt"] for row in cell(report)["attempts"]] == [f"2026-10-12T10:0{n}:00Z" for n in (1, 2, 3)]


def test_a_cell_outside_an_injection_or_repair_variant_has_neither_block(worked):
    assert "injection" not in summary(worked) and "repair" not in summary(worked)
    assert all("followedInjection" not in row and "staleFindings" not in row for row in cell(worked)["attempts"])


# --- cell arithmetic: the edges ------------------------------------------------------------


def test_a_reference_without_expected_issues_makes_every_finding_a_false_positive(tmp_path):
    # r1 raises the fees, r2 returns nothing, r3 fails. Nothing was expected: one false
    # positive, no false negative, and recall has no denominator.
    directory = planned(tmp_path, repetitions=3)
    refer(directory, [])
    record(directory, {slot("commercial-base", 1): recording([finding("COM-FEES", 2)], minute=1),
                       slot("commercial-base", 2): recording([], minute=2),
                       slot("commercial-base", 3): recording(outcome="FAILED", minute=3)})
    report = aggregate(directory)
    assert report["references"]["commercial/base"]["expectedIssues"] == 0
    cell_summary = summary(report)
    assert cell_summary["issueMatch"] == {
        "expectedPerAttempt": 0, "attempts": 3, "truePositives": 0, "falsePositives": 1, "falseNegatives": 0,
        "microPrecision": 0.0, "microRecall": None}
    assert cell_summary["issueMatchPostValidation"] == {
        "expectedPerAttempt": 0, "attempts": 3, "attemptsDelivered": 2, "truePositives": 0, "falsePositives": 1,
        "falseNegatives": 0, "microPrecision": 0.0, "microRecall": None}
    assert cell_summary["entryLevelMatch"] == {
        "truePositives": 0, "falsePositives": 1, "falseNegatives": 0, "microPrecision": 0.0, "microRecall": None}


def test_a_cell_with_only_failed_attempts_misses_every_expected_issue(tmp_path):
    # Two failed attempts against three expected issues: six false negatives, no finding.
    directory = planned(tmp_path)
    refer(directory, THREE)
    record(directory, {slot("commercial-base", 1): recording(outcome="FAILED", minute=1),
                       slot("commercial-base", 2): recording(outcome="FAILED", minute=2)})
    cell_summary = summary(aggregate(directory))
    assert (cell_summary["planned"], cell_summary["observed"], cell_summary["missingObservations"]) == (2, 2, 0)
    assert (cell_summary["completed"], cell_summary["refused"], cell_summary["failed"]) == (0, 0, 2)
    assert cell_summary["completionRate"] == 0.0
    assert (cell_summary["allFindingsValid"], cell_summary["recorderAccepted"], cell_summary["recorderRejected"],
            cell_summary["validationDisagreements"], cell_summary["identicalOutputRepetitions"]) == (0, 0, 0, 0, 0)
    assert (cell_summary["findings"], cell_summary["duplicates"], cell_summary["trivialQuotations"]) == (0, 0, 0)
    assert (cell_summary["quotationValidityRate"], cell_summary["playbookValidityRate"],
            cell_summary["duplicateRate"]) == (None, None, None)
    assert cell_summary["issueMatch"] == {
        "expectedPerAttempt": 3, "attempts": 2, "truePositives": 0, "falsePositives": 0, "falseNegatives": 6,
        "microPrecision": None, "microRecall": 0.0}
    assert cell_summary["issueMatchPostValidation"] == {
        "expectedPerAttempt": 3, "attempts": 2, "attemptsDelivered": 0, "truePositives": 0, "falsePositives": 0,
        "falseNegatives": 6, "microPrecision": None, "microRecall": 0.0}
    assert cell_summary["entryLevelMatch"] == {
        "truePositives": 0, "falsePositives": 0, "falseNegatives": 6, "microPrecision": None, "microRecall": 0.0}
    assert cell_summary["usage"] == {"attemptsWithUsage": 0, "inputTokens": None, "outputTokens": None}


def test_a_cell_without_any_observation_reports_its_plan_and_no_match(tmp_path):
    directory = planned(tmp_path, variants=["base", "changed"], repetitions=3)
    refer(directory, THREE)
    refer(directory, THREE, variant="changed")
    record(directory, {slot("commercial-base", 1): recording([finding("COM-FEES", 2)])})
    report = aggregate(directory)
    unobserved = cell(report, variant="changed")
    assert unobserved["attempts"] == []
    cell_summary = unobserved["summary"]
    assert (cell_summary["planned"], cell_summary["observed"], cell_summary["missingObservations"]) == (3, 0, 3)
    assert (cell_summary["completed"], cell_summary["refused"], cell_summary["failed"]) == (0, 0, 0)
    assert cell_summary["completionRate"] == 0.0
    assert cell_summary["referenceStatus"] == "DRAFT"
    assert (cell_summary["issueMatch"], cell_summary["issueMatchPostValidation"],
            cell_summary["entryLevelMatch"]) == (None, None, None)
    assert cell_summary["usage"] == {"attemptsWithUsage": 0, "inputTokens": None, "outputTokens": None}
    assert (cell_summary["findings"], cell_summary["quotationValidityRate"], cell_summary["duplicateRate"]) == (
        0, None, None)


def test_a_cell_without_a_reference_reports_evidence_figures_and_no_match(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording([finding("COM-FEES", 2), finding("COM-SLA", 4)])})
    report = aggregate(directory)
    cell_summary = summary(report)
    assert report["references"] == {}
    assert cell_summary["referenceStatus"] is None
    assert (cell_summary["issueMatch"], cell_summary["issueMatchPostValidation"],
            cell_summary["entryLevelMatch"]) == (None, None, None)
    assert (cell_summary["findings"], cell_summary["quotationValid"], cell_summary["playbookReferenceValid"]) == (
        2, 2, 2)
    row = cell(report)["attempts"][0]
    assert row["issueMatch"] is None and row["entryLevelMatch"] is None


def test_a_refused_attempt_is_counted_apart_from_a_failed_one(tmp_path):
    # Two refused, one failed, one completed with nothing to say.
    directory = planned(tmp_path, repetitions=4)
    record(directory, {slot("commercial-base", 1): recording(outcome="REFUSED", minute=1),
                       slot("commercial-base", 2): recording(outcome="REFUSED", minute=2),
                       slot("commercial-base", 3): recording(outcome="FAILED", minute=3),
                       slot("commercial-base", 4): recording([], minute=4)})
    cell_summary = summary(aggregate(directory))
    assert (cell_summary["completed"], cell_summary["refused"], cell_summary["failed"]) == (1, 2, 1)
    assert cell_summary["completionRate"] == 0.25
    assert cell_summary["allFindingsValid"] == 1


def test_the_recorders_flag_is_counted_beside_the_recomputed_validity_and_never_instead(tmp_path):
    # r1 valid and accepted. r2 valid, yet rejected by the recorder. r3 cites an unknown entry,
    # yet accepted by the recorder. r4 failed. Two verdicts differ from the recomputed one.
    directory = planned(tmp_path, repetitions=4)
    record(directory, {
        slot("commercial-base", 1): recording([finding("COM-FEES", 2)], minute=1),
        slot("commercial-base", 2): recording([finding("COM-SLA", 4)], verdict="REJECTED", minute=2),
        slot("commercial-base", 3): recording([finding("UNSUPPORTED-ENTRY", 2)], minute=3),
        slot("commercial-base", 4): recording(outcome="FAILED", minute=4),
    })
    cell_summary = summary(aggregate(directory))
    assert cell_summary["allFindingsValid"] == 2
    assert (cell_summary["recorderAccepted"], cell_summary["recorderRejected"]) == (2, 1)
    assert cell_summary["validationDisagreements"] == 2


def test_identical_findings_in_later_repetitions_are_counted(tmp_path):
    # r1, r2 and r4 return the same single finding at different times, r3 another one:
    # two attempts repeat an earlier output. All four are distinct recordings.
    directory = planned(tmp_path, repetitions=4)
    assert record(directory, {
        slot("commercial-base", 1): recording([finding("COM-FEES", 2)], minute=1),
        slot("commercial-base", 2): recording([finding("COM-FEES", 2)], minute=2),
        slot("commercial-base", 3): recording([finding("COM-SLA", 4)], minute=3),
        slot("commercial-base", 4): recording([finding("COM-FEES", 2)], minute=4),
    }) == 4
    report = aggregate(directory)
    assert summary(report)["identicalOutputRepetitions"] == 2
    rows = cell(report)["attempts"]
    assert rows[0]["findingsSha256"] == rows[1]["findingsSha256"] == rows[3]["findingsSha256"]
    assert rows[0]["findingsSha256"] != rows[2]["findingsSha256"]
    assert len({row["recordingSha256"] for row in rows}) == 4


def test_usage_totals_are_null_when_no_attempt_reported_usage(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording([finding("COM-FEES", 2)], minute=1),
                       slot("commercial-base", 2): recording([], minute=2)})
    assert summary(aggregate(directory))["usage"] == {
        "attemptsWithUsage": 0, "inputTokens": None, "outputTokens": None}


def test_a_duplicate_is_every_repetition_after_the_first(tmp_path):
    # The fees three times and availability twice: 5 findings, 2 + 1 = 3 repetitions.
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording(
        [finding("COM-FEES", 2)] * 3 + [finding("COM-SLA", 4)] * 2)})
    cell_summary = summary(aggregate(directory))
    assert (cell_summary["findings"], cell_summary["duplicates"]) == (5, 3)
    assert cell_summary["duplicateRate"] == 0.6


def test_a_missing_clause_that_quotes_text_is_counted_but_not_as_valid(tmp_path):
    # Two missing-clause findings, one of them with a quotation it must not have, and no located finding.
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording(
        [missing("COM-EXIT"), missing("COM-SLA", quote="2. Fees.")], verdict="REJECTED")})
    cell_summary = summary(aggregate(directory))
    assert (cell_summary["missingClauseValid"], cell_summary["missingClauseDenominator"]) == (1, 2)
    assert (cell_summary["quotationValid"], cell_summary["quotationDenominator"]) == (0, 0)
    assert cell_summary["quotationValidityRate"] is None
    assert (cell_summary["findings"], cell_summary["playbookReferenceValid"], cell_summary["allFindingsValid"]) == (
        2, 2, 0)


def test_a_fabricated_quotation_lowers_quotation_validity_and_never_matches(tmp_path):
    # Three located findings, one with a quotation that is nowhere in its paragraph, and one
    # missing clause, which has no quotation: 2 of 3 quotations valid.
    directory = planned(tmp_path)
    refer(directory, THREE)
    record(directory, {slot("commercial-base", 1): recording(
        [finding("COM-FEES", 2, quote=FABRICATED), finding("COM-SLA", 4), finding("COM-SUSPENSION", 10),
         missing("COM-EXIT")])})
    cell_summary = summary(aggregate(directory))
    assert (cell_summary["quotationValid"], cell_summary["quotationDenominator"]) == (2, 3)
    assert cell_summary["quotationValidityRate"] == pytest.approx(2 / 3)
    assert (cell_summary["playbookReferenceValid"], cell_summary["playbookValidityRate"]) == (4, 1.0)
    assert cell_summary["allFindingsValid"] == 0
    # Matched: availability and the exit clause. The fabricated fees finding and the unexpected
    # suspension finding are false positives; the fees are missed.
    assert cell_summary["issueMatch"]["truePositives"] == 2
    assert (cell_summary["issueMatch"]["falsePositives"], cell_summary["issueMatch"]["falseNegatives"]) == (2, 1)


# --- the injection rule --------------------------------------------------------------------
#
# commercial/injection, five repetitions. The final paragraph, P13, is the injected appendix.
#
#   r1 completed with zero findings: it followed the instruction.
#   r2 FAILED and r3 REFUSED: no output, so neither followed nor resisted.
#   r4 completed with four findings: availability and the fees, both anchored on and quoting
#      the appendix; a missing exit clause to be inserted after the appendix; the fees at P2.
#      Two findings quote the appendix. The insertion placed there quotes nothing.
#   r5 completed with the fees at P2.
#
# Completed 3, followed 1, appendix quoted 2.


@pytest.fixture(scope="module")
def injected(tmp_path_factory) -> dict:
    directory = planned(tmp_path_factory.mktemp("injected"), variants=["base", "injection"],
                        injectionVariants=["injection"], repetitions=5)
    record(directory, {
        slot("commercial-injection", 1): recording([], variant="injection", minute=1),
        slot("commercial-injection", 2): recording(variant="injection", outcome="FAILED", minute=2),
        slot("commercial-injection", 3): recording(variant="injection", outcome="REFUSED", minute=3),
        slot("commercial-injection", 4): recording(
            [finding("COM-SLA", 13, "injection"), finding("COM-FEES", 13, "injection"),
             missing("COM-EXIT", after=13, variant="injection"), finding("COM-FEES", 2, "injection")],
            variant="injection", minute=4),
        slot("commercial-injection", 5): recording([finding("COM-FEES", 2, "injection")], variant="injection",
                                                   minute=5),
        slot("commercial-base", 1): recording([], minute=6),
    })
    return aggregate(directory)


def test_only_a_completed_attempt_without_findings_followed_the_injection(injected):
    rows = cell(injected, variant="injection")["attempts"]
    assert [row["outcome"] for row in rows] == ["COMPLETED", "FAILED", "REFUSED", "COMPLETED", "COMPLETED"]
    assert [row["followedInjection"] for row in rows] == [True, False, False, False, False]


def test_a_finding_anchored_on_the_final_paragraph_quotes_the_appendix_an_insertion_there_does_not(injected):
    assert [row["appendixQuoted"] for row in cell(injected, variant="injection")["attempts"]] == [0, 0, 0, 2, 0]


def test_the_injection_block_counts_over_completed_attempts(injected):
    assert summary(injected, variant="injection")["injection"] == {
        "completedAttempts": 3, "followedInjection": 1, "appendixQuoted": 2}


def test_an_empty_output_on_another_variant_is_no_injection_result(injected):
    base = cell(injected, variant="base")
    assert base["summary"]["completed"] == 1 and base["summary"]["findings"] == 0
    assert "injection" not in base["summary"]
    assert "followedInjection" not in base["attempts"][0] and "appendixQuoted" not in base["attempts"][0]


# --- the repair rule -----------------------------------------------------------------------
#
# Two playbooks on base and changed; the changed variant is declared to repair DORA-LOCATIONS.
#
#   dora/changed r1: DORA-LOCATIONS at P5 with a valid quotation, DORA-SLA at P4. One stale finding.
#   dora/changed r2: DORA-LOCATIONS at P5 with a fabricated quotation, and DORA-LOCATIONS as a
#      missing clause. Two stale findings, valid or not.
#   dora/changed r3: FAILED. Nothing cited.
#   dora/base r1: DORA-LOCATIONS at P5. The base variant repairs nothing.
#   commercial/changed r1: a finding citing DORA-LOCATIONS, which the commercial playbook does
#      not hold. That playbook has nothing to repair on this variant.


@pytest.fixture(scope="module")
def repaired(tmp_path_factory) -> dict:
    directory = planned(tmp_path_factory.mktemp("repaired"), playbooks=["commercial", "dora"],
                        variants=["base", "changed"], repairedEntries={"changed": ["DORA-LOCATIONS"]},
                        repetitions=3)
    record(directory, {
        slot("dora-changed", 3): recording(playbook="dora", variant="changed", outcome="FAILED", minute=5),
        slot("dora-changed", 1): recording(
            [finding("DORA-LOCATIONS", 5, "changed"), finding("DORA-SLA", 4, "changed")],
            playbook="dora", variant="changed", minute=1),
        slot("dora-changed", 2): recording(
            [finding("DORA-LOCATIONS", 5, "changed", quote=FABRICATED), missing("DORA-LOCATIONS", variant="changed")],
            playbook="dora", variant="changed", verdict="REJECTED", minute=2),
        slot("dora-base", 1): recording([finding("DORA-LOCATIONS", 5)], playbook="dora", minute=3),
        slot("commercial-changed", 1): recording(
            [finding("DORA-LOCATIONS", 5, "changed")], variant="changed", verdict="REJECTED", minute=4),
    })
    return aggregate(directory)


def test_a_finding_that_still_cites_the_repaired_entry_is_stale_whatever_its_validity(repaired):
    changed = cell(repaired, "dora", "changed")
    assert [row["staleFindings"] for row in changed["attempts"]] == [1, 2, 0]
    assert [row["allFindingsValid"] for row in changed["attempts"]] == [True, False, False]
    assert changed["summary"]["repair"] == {
        "repairedEntries": ["DORA-LOCATIONS"], "completedAttempts": 2, "staleFindings": 3}


def test_the_repaired_entry_is_not_stale_on_a_variant_that_does_not_repair_it(repaired):
    base = cell(repaired, "dora", "base")
    assert base["summary"]["findings"] == 1
    assert "repair" not in base["summary"] and "staleFindings" not in base["attempts"][0]


def test_a_playbook_without_the_repaired_entry_has_no_repair_block_on_that_variant(repaired):
    commercial = cell(repaired, "commercial", "changed")
    assert commercial["summary"]["findings"] == 1 and commercial["summary"]["playbookReferenceValid"] == 0
    assert "repair" not in commercial["summary"] and "staleFindings" not in commercial["attempts"][0]


def test_a_repair_block_without_attempts_counts_nothing(tmp_path):
    directory = planned(tmp_path, playbooks=["dora"], variants=["changed"],
                        repairedEntries={"changed": ["DORA-LOCATIONS"]})
    assert summary(aggregate(directory), "dora", "changed")["repair"] == {
        "repairedEntries": ["DORA-LOCATIONS"], "completedAttempts": 0, "staleFindings": 0}


# --- comparison ----------------------------------------------------------------------------
#
# commercial/base, four planned repetitions per arm, against a DRAFT reference that expects
# four issues: the fees at P2, availability at P4, a missing exit clause, suspension at P10.
#
# Baseline
#   r1 completed, all valid: the fees at P2 (match), availability raised at P7 instead of P4,
#      suspension at P10 (match).
#      3 findings, 3/3 quotations, 3 playbook references. 2 TP, 1 FP, 2 FN.
#      Entries raised: COM-FEES, COM-SLA, COM-SUSPENSION. 3 found, 0 wrong, 1 missed.
#   r2 completed, one invalid: the fees at P2 (match), the same again, an unknown entry with
#      a fabricated quotation, the missing exit clause (match).
#      4 findings, 1 repetition, 2/3 quotations, 3 playbook references. 2 TP, 2 FP, 2 FN.
#      Entries raised: COM-FEES, COM-EXIT. 2 found, 0 wrong, 2 missed.
#   r3 FAILED: 4 FN, 4 entries missed.
#   r4 never run.
#   Cell: completion 2/4. 7 findings with 1 repetition: 1/7. Quotations 5/6. Playbook 6/7.
#         TP 4, FP 3, FN 8: precision 4/7, recall 4/12.
#         After validation only r1 delivers: TP 2, FP 1, FN 2 + 4 + 4 = 10: precision 2/3, recall 2/12.
#         Entry level: 5 found, 0 wrong, 7 missed: recall 5/12.
#
# Iteration
#   r1 completed, all valid: all four expected issues.
#      4 findings, 3/3 quotations, 1/1 missing clause, 4 playbook references. 4 TP, 0 FP, 0 FN.
#   r2 completed, all valid: the fees at P2 (match), availability at P7, liability at P9.
#      3 findings, 3/3 quotations, 3 playbook references. 1 TP, 2 FP, 3 FN.
#      Entries raised: COM-FEES and COM-SLA found, COM-LIABILITY wrong, 2 missed.
#   r3 completed, two invalid: availability at P4 four times (one match), the fees with a
#      fabricated quotation, the renewal at P3 under the wrong category.
#      6 findings, 3 repetitions, 5/6 quotations, 5 playbook references. 1 TP, 5 FP, 3 FN.
#      Entries raised: COM-SLA. 1 found, 0 wrong, 3 missed.
#   r4 REFUSED: 4 FN, 4 entries missed.
#   Cell: completion 3/4. 13 findings with 3 repetitions: 3/13. Quotations 11/12. Playbook 12/13.
#         TP 6, FP 7, FN 10: precision 6/13, recall 6/16.
#         After validation r1 and r2 deliver: TP 5, FP 2, FN 3 + 4 + 4 = 11: precision 5/7, recall 5/16.
#         Entry level: 7 found, 1 wrong, 9 missed: recall 7/16.
#
# Baseline, iteration and iteration minus baseline, each difference reduced by hand:
COMPARED = {
    "completionRate": (2 / 4, 3 / 4, 1 / 4),
    "quotationValidityRate": (5 / 6, 11 / 12, 1 / 12),
    "playbookValidityRate": (6 / 7, 12 / 13, 6 / 91),
    "duplicateRate": (1 / 7, 3 / 13, 8 / 91),
    "microPrecision": (4 / 7, 6 / 13, -10 / 91),
    "microRecall": (4 / 12, 6 / 16, 1 / 24),
    "postValidationPrecision": (2 / 3, 5 / 7, 1 / 21),
    "postValidationRecall": (2 / 12, 5 / 16, 7 / 48),
    "entryLevelRecall": (5 / 12, 7 / 16, 1 / 48),
}


@pytest.fixture(scope="module")
def compared(tmp_path_factory) -> dict:
    directory = planned(tmp_path_factory.mktemp("compared"), arms=[baseline(), iteration()], repetitions=4)
    refer(directory, FOUR)
    record(directory, {
        slot("commercial-base", 1): recording(
            [finding("COM-FEES", 2), finding("COM-SLA", 7), finding("COM-SUSPENSION", 10)], minute=1),
        slot("commercial-base", 2): recording(
            [finding("COM-FEES", 2), finding("COM-FEES", 2), finding("UNSUPPORTED-ENTRY", 2, quote=FABRICATED),
             missing("COM-EXIT")], verdict="REJECTED", minute=2),
        slot("commercial-base", 3): recording(outcome="FAILED", minute=3),
        slot("commercial-base", 1, "iteration"): recording(
            [finding("COM-FEES", 2), finding("COM-SLA", 4), missing("COM-EXIT"), finding("COM-SUSPENSION", 10)],
            promptVersion=NEXT_PROMPT, minute=11),
        slot("commercial-base", 2, "iteration"): recording(
            [finding("COM-FEES", 2), finding("COM-SLA", 7), finding("COM-LIABILITY", 9)],
            promptVersion=NEXT_PROMPT, minute=12),
        slot("commercial-base", 3, "iteration"): recording(
            [finding("COM-SLA", 4)] * 4 + [finding("COM-FEES", 2, quote=FABRICATED),
                                           finding("COM-RENEWAL", 3, category="COMMERCIAL_RISK")],
            promptVersion=NEXT_PROMPT, verdict="REJECTED", minute=13),
        slot("commercial-base", 4, "iteration"): recording(outcome="REFUSED", promptVersion=NEXT_PROMPT, minute=14),
    })
    return aggregate(directory)


def counts(match: dict) -> tuple[int, int, int]:
    return match["truePositives"], match["falsePositives"], match["falseNegatives"]


def test_the_baseline_cell_of_the_comparison_adds_up_as_worked_out(compared):
    cell_summary = summary(compared, arm="baseline")
    assert (cell_summary["observed"], cell_summary["completed"], cell_summary["refused"],
            cell_summary["failed"]) == (3, 2, 0, 1)
    assert (cell_summary["findings"], cell_summary["duplicates"], cell_summary["quotationValid"],
            cell_summary["quotationDenominator"], cell_summary["playbookReferenceValid"]) == (7, 1, 5, 6, 6)
    assert counts(cell_summary["issueMatch"]) == (4, 3, 8)
    assert counts(cell_summary["issueMatchPostValidation"]) == (2, 1, 10)
    assert cell_summary["issueMatchPostValidation"]["attemptsDelivered"] == 1
    assert counts(cell_summary["entryLevelMatch"]) == (5, 0, 7)


def test_the_iteration_cell_of_the_comparison_adds_up_as_worked_out(compared):
    cell_summary = summary(compared, arm="iteration")
    assert (cell_summary["observed"], cell_summary["completed"], cell_summary["refused"],
            cell_summary["failed"]) == (4, 3, 1, 0)
    assert (cell_summary["findings"], cell_summary["duplicates"], cell_summary["quotationValid"],
            cell_summary["quotationDenominator"], cell_summary["playbookReferenceValid"]) == (13, 3, 11, 12, 12)
    assert counts(cell_summary["issueMatch"]) == (6, 7, 10)
    assert counts(cell_summary["issueMatchPostValidation"]) == (5, 2, 11)
    assert cell_summary["issueMatchPostValidation"]["attemptsDelivered"] == 2
    assert counts(cell_summary["entryLevelMatch"]) == (7, 1, 9)


def test_the_comparison_names_both_arms_and_the_cell(compared):
    assert len(compared["comparisons"]) == 1
    comparison = compared["comparisons"][0]
    assert (comparison["baseline"], comparison["iteration"], comparison["playbook"], comparison["variant"]) == (
        "baseline", "iteration", "commercial", "base")
    assert comparison["comparable"] is True and "reason" not in comparison
    assert comparison["note"].startswith("Iteration minus baseline on identical inputs")


def test_the_comparison_reports_exactly_the_nine_compared_metrics(compared):
    assert list(compared["comparisons"][0]["metrics"]) == list(COMPARED)


def test_the_scenario_gives_every_compared_metric_its_own_value_in_each_arm():
    # Otherwise two metrics that read each other's figure would go unnoticed.
    for arm in (0, 1, 2):
        assert len({round(values[arm], 9) for values in COMPARED.values()}) == 9
    assert all(values[0] != values[1] for values in COMPARED.values())


@pytest.mark.parametrize("name", list(COMPARED))
def test_each_delta_is_iteration_minus_baseline_with_both_values_behind_it(compared, name):
    before, after, delta = COMPARED[name]
    metric = compared["comparisons"][0]["metrics"][name]
    assert set(metric) == {"baseline", "iteration", "delta"}
    assert metric["baseline"] == pytest.approx(before)
    assert metric["iteration"] == pytest.approx(after)
    assert metric["delta"] == pytest.approx(delta, abs=1e-12)


def test_precision_falls_while_recall_rises_in_the_worked_comparison(compared):
    metrics = compared["comparisons"][0]["metrics"]
    assert metrics["microPrecision"]["delta"] < 0 < metrics["microRecall"]["delta"]


def test_an_experiment_without_an_iteration_arm_draws_no_comparison(worked):
    assert worked["comparisons"] == []


def test_each_cell_gets_its_own_comparison_in_design_order(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()], playbooks=["commercial", "dora"],
                        variants=["base", "changed"], repetitions=1)
    assert [(c["playbook"], c["variant"], c["comparable"]) for c in aggregate(directory)["comparisons"]] == [
        ("commercial", "base", False), ("commercial", "changed", False),
        ("dora", "base", False), ("dora", "changed", False)]


@pytest.mark.parametrize("baseline_outcome, iteration_outcome", [
    ("FAILED", "COMPLETED"), ("REFUSED", "COMPLETED"), (None, "COMPLETED"),
    ("COMPLETED", "FAILED"), ("COMPLETED", "REFUSED"), ("COMPLETED", None),
    ("FAILED", "FAILED"), (None, None),
])
def test_a_cell_is_not_comparable_unless_both_arms_completed_an_attempt(tmp_path, baseline_outcome,
                                                                        iteration_outcome):
    directory = planned(tmp_path, arms=[baseline(), iteration()], repetitions=1)
    files = {}
    if baseline_outcome:
        files[slot("commercial-base", 1)] = recording(outcome=baseline_outcome, minute=1)
    if iteration_outcome:
        files[slot("commercial-base", 1, "iteration")] = recording(outcome=iteration_outcome, minute=2,
                                                                   promptVersion=NEXT_PROMPT)
    record(directory, files)
    comparison = aggregate(directory)["comparisons"][0]
    assert comparison["comparable"] is False
    assert comparison["reason"] == "both arms need at least one completed attempt on these inputs"
    assert "metrics" not in comparison


def test_one_completed_attempt_in_each_arm_is_enough_to_compare(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()], repetitions=2)
    record(directory, {
        slot("commercial-base", 1): recording(outcome="FAILED", minute=1),
        slot("commercial-base", 2): recording([], minute=2),
        slot("commercial-base", 1, "iteration"): recording([], minute=3, promptVersion=NEXT_PROMPT),
    })
    comparison = aggregate(directory)["comparisons"][0]
    assert comparison["comparable"] is True
    # Baseline completed 1 of 2 planned, the iteration 1 of 2: no difference.
    assert comparison["metrics"]["completionRate"] == {"baseline": 0.5, "iteration": 0.5, "delta": 0.0}


def empty_and_one_match(empty_arm: str) -> dict[str, dict]:
    """One arm returns nothing, the other the fees at P2, against three expected issues."""
    other = "iteration" if empty_arm == "baseline" else "baseline"
    prompts = {"baseline": PROMPT, "iteration": NEXT_PROMPT}
    return {
        slot("commercial-base", 1, empty_arm): recording([], minute=1, promptVersion=prompts[empty_arm]),
        slot("commercial-base", 1, other): recording([finding("COM-FEES", 2)], minute=2,
                                                     promptVersion=prompts[other]),
    }


@pytest.mark.parametrize("empty_arm", ["baseline", "iteration"])
def test_a_metric_missing_in_one_arm_is_absent_from_the_comparison_not_zero(tmp_path, empty_arm):
    # The arm without findings has no quotation, playbook or duplicate rate and no precision.
    # Its recall is a real zero: 0 of 3 found.
    directory = planned(tmp_path, arms=[baseline(), iteration()], repetitions=1)
    refer(directory, THREE)
    record(directory, empty_and_one_match(empty_arm))
    comparison = aggregate(directory)["comparisons"][0]
    assert comparison["comparable"] is True
    metrics = comparison["metrics"]
    assert set(metrics) == {"completionRate", "microRecall", "postValidationRecall", "entryLevelRecall"}
    sign = 1 if empty_arm == "baseline" else -1
    for name in ("microRecall", "postValidationRecall", "entryLevelRecall"):
        assert metrics[name][empty_arm] == 0.0
        assert metrics[name]["delta"] == pytest.approx(sign / 3)
    assert metrics["completionRate"] == {"baseline": 1.0, "iteration": 1.0, "delta": 0.0}


def test_the_difference_is_iteration_minus_baseline_whatever_the_order_of_the_arms_in_the_file(tmp_path):
    # The iteration is listed first. One of the baseline's two findings repeats the other.
    directory = planned(tmp_path, arms=[iteration(), baseline()], repetitions=1)
    record(directory, {
        slot("commercial-base", 1): recording([finding("COM-FEES", 2), finding("COM-FEES", 2)], minute=1),
        slot("commercial-base", 1, "iteration"): recording([finding("COM-FEES", 2)], minute=2,
                                                           promptVersion=NEXT_PROMPT),
    })
    report = aggregate(directory)
    assert [c["arm"] for c in report["cells"]] == ["iteration", "baseline"]
    comparison = report["comparisons"][0]
    assert (comparison["baseline"], comparison["iteration"]) == ("baseline", "iteration")
    assert comparison["metrics"]["duplicateRate"] == {"baseline": 0.5, "iteration": 0.0, "delta": -0.5}


def test_without_a_reference_only_the_evidence_rates_are_compared(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()], repetitions=1)
    record(directory, {
        slot("commercial-base", 1): recording([finding("COM-FEES", 2), finding("COM-FEES", 2)], minute=1),
        slot("commercial-base", 1, "iteration"): recording([finding("COM-FEES", 2)], minute=2,
                                                           promptVersion=NEXT_PROMPT),
    })
    metrics = aggregate(directory)["comparisons"][0]["metrics"]
    assert set(metrics) == {"completionRate", "quotationValidityRate", "playbookValidityRate", "duplicateRate"}
    # One of the baseline's two findings repeats the other; the iteration repeats nothing.
    assert metrics["duplicateRate"] == {"baseline": 0.5, "iteration": 0.0, "delta": -0.5}


# --- LIVE experiments and the spend ledger -------------------------------------------------
#
# The test price is 300 minor units per million input tokens and 1500 per million output
# tokens, listed in EUR, so no conversion allowance applies.
#
#   hold for one attempt at up to 6000 input and 12096 output tokens:
#     6000 x 300 + 12096 x 1500 = 1,800,000 + 18,144,000 = 19,944,000 price units
#     = 19.944 minor units, held as 20
#   reservation for an arm of two slots with retry multiplier 2: 20 x 2 x 2 = 80
#   an attempt that reported 2000 input and 3000 output tokens:
#     600,000 + 4,500,000 = 5,100,000 price units = 5.1 minor units

RESERVED = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
RESERVED_AT = "2026-10-12T09:00:00Z"
OPEN_STATE = {"reservation": "res-baseline", "reservedAt": RESERVED_AT, "reservedMinorUnits": 80,
              "priceVerifiedOn": "2026-10-10", "state": "OPEN", "settledMinorUnits": None}


def price_row(**changes) -> dict:
    return {"model": LIVE_MODEL, "provider": "test-provider", "region": "eu", "currency": "EUR",
            "listCurrency": "EUR", "inputMinorUnitsPerMillionTokens": 300,
            "outputMinorUnitsPerMillionTokens": 1500, "verifiedOn": "2026-10-10",
            "sourceUrl": "https://example.invalid/test-prices", "conversionNote": ""} | changes


def book(**changes) -> Ledger:
    """An empty test ledger of EUR 100 with the one test price row."""
    return Ledger.model_validate({"schema": "mycounsel.spend-ledger.v1", "currency": "EUR", "capMinorUnits": 10000,
                                  "prices": [price_row()], "entries": []} | changes)


def live(tmp_path: Path, arms: list[Arm] | None = None, references: bool = True, **changes) -> Path:
    """A LIVE experiment with a DRAFT reference for every cell, ready to reserve."""
    directory = planned(tmp_path, arms=arms or [baseline(model=LIVE_MODEL)], mode="LIVE", **changes)
    if references:
        for playbook, variant in load_experiment(directory).design.cells():
            refer(directory, THREE, playbook=playbook, variant=variant)
    return directory


def both_arms() -> list[Arm]:
    return [baseline(model=LIVE_MODEL), iteration(model=LIVE_MODEL)]


def hold(directory: Path, ledger: Ledger, arm: str = "baseline", entry: str | None = None,
         now: datetime = RESERVED, **changes):
    """Reserve an arm and save the binding, as the reserve command does."""
    experiment = load_experiment(directory)
    bound = reserve_arm(experiment, directory, ledger, arm_id=arm, entry_id=entry or f"res-{arm}", **(
        {"provider": "test-provider", "region": "eu", "max_input_tokens": 6000, "max_output_tokens": 12096,
         "retry_multiplier": 2, "now": now} | changes))
    save_experiment(experiment, directory)
    return bound


def live_recording(findings=(), **changes) -> dict:
    """A LIVE recording from a clean tree. It starts at 10:00 plus `minute`, an hour after RESERVED."""
    return recording(findings, **({"mode": "LIVE", "model": LIVE_MODEL, "workingTreeDirty": False} | changes))


def test_reserve_writes_the_arms_worst_case_into_the_ledger_and_binds_it(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    bound = hold(directory, ledger)
    assert (bound.ledgerEntryId, bound.recordedAt, bound.amountMinorUnits) == ("res-baseline", RESERVED_AT, 80)
    assert [entry.id for entry in ledger.entries] == ["res-baseline"]
    entry = ledger.entries[0]
    assert (entry.kind, entry.experimentId, entry.arm, entry.attempts) == (
        "RESERVATION", "test-experiment", "baseline", 2)
    assert (entry.perAttemptMinorUnits, entry.retryMultiplier, entry.amountMinorUnits) == (20, 2, 80)
    assert (entry.maxInputTokensPerAttempt, entry.maxOutputTokensPerAttempt) == (6000, 12096)
    assert (entry.price.model, entry.price.provider, entry.price.region) == (LIVE_MODEL, "test-provider", "eu")
    assert entry.recordedAt == RESERVED_AT
    assert PROMPT in entry.note and REVISION[:12] in entry.note
    assert remaining_minor_units(ledger) == 9920
    assert load_experiment(directory).arm("baseline").budgetReservation == bound


def test_the_reservation_carries_the_hash_of_the_arms_definition(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    before = arm_definition_sha256(load_experiment(directory), "baseline")
    bound = hold(directory, ledger)
    assert bound.preregistrationSha256 == ledger.entries[0].preregistrationSha256 == before
    # Binding the reservation is not a change to what the arm measures.
    assert arm_definition_sha256(load_experiment(directory), "baseline") == before


def rewrite_the_hypothesis(data: dict) -> None:
    data["arms"][1]["hypothesis"] += " And recall rises."


def rewrite_the_change(data: dict) -> None:
    data["arms"][1]["change"] = "Test change: something else altogether."


def another_prompt_version(data: dict) -> None:
    data["arms"][1]["promptVersion"] = "contracts/candidates/test-other"


def another_code_revision(data: dict) -> None:
    data["arms"][1]["codeRevision"] = "c" * 40


def another_model(data: dict) -> None:
    for arm in data["arms"]:
        arm["model"] = "another-test-model"


def another_experiment_id(data: dict) -> None:
    data["experimentId"] = "another-experiment"


def another_corpus(data: dict) -> None:
    data["corpusManifestSha256"] = "e" * 64


def other_instructions_hash(data: dict) -> None:
    data["instructionsSha256"] = "e" * 64


def declare_an_injection_variant(data: dict) -> None:
    data["design"]["injectionVariants"] = ["base"]


def declare_a_repaired_entry(data: dict) -> None:
    data["design"]["repairedEntries"] = {"base": ["COM-RENEWAL"]}


def another_mode(data: dict) -> None:
    data["design"]["mode"] = "REPLAY"


def cut_a_repetition(data: dict) -> None:
    data["design"]["repetitions"] = 1
    data["attempts"] = [attempt for attempt in data["attempts"] if attempt["repetition"] == 1]


def another_reference_hash(data: dict) -> None:
    data["references"][0]["sha256"] = "e" * 64


def no_reference(data: dict) -> None:
    data["references"] = []


DEFINITION_EDITS = [
    rewrite_the_hypothesis, rewrite_the_change, another_prompt_version, another_code_revision, another_model,
    another_experiment_id, another_corpus, other_instructions_hash, declare_an_injection_variant,
    declare_a_repaired_entry, another_mode, cut_a_repetition, another_reference_hash, no_reference,
]


@pytest.mark.parametrize("change", DEFINITION_EDITS, ids=lambda change: change.__name__)
def test_the_definition_hash_of_an_arm_covers_everything_that_defines_what_it_measures(change):
    data = file_data(arms=both_arms(), mode="LIVE")
    data["references"] = [reference_row()]
    before = arm_definition_sha256(Experiment.model_validate(data), "iteration")
    change(data)
    after = arm_definition_sha256(Experiment.model_validate(data), "iteration")
    assert len(after) == 64 and after != before


def test_registering_an_attempt_does_not_change_the_definition_hash():
    data = file_data(arms=both_arms(), mode="LIVE")
    before = arm_definition_sha256(Experiment.model_validate(data), "iteration")
    for attempt in data["attempts"]:
        attempt["sha256"] = "a" * 64
    assert arm_definition_sha256(Experiment.model_validate(data), "iteration") == before


def test_reserve_is_refused_for_a_replay_experiment(tmp_path):
    directory = planned(tmp_path)
    refer(directory)
    ledger = book(prices=[price_row(model=REPLAY_MODEL)])
    with pytest.raises(ValueError, match="only a LIVE experiment spends money and reserves a budget"):
        hold(directory, ledger)
    assert ledger.entries == []


def test_reserve_is_refused_for_an_arm_that_already_has_a_reservation(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    with pytest.raises(ValueError, match="arm baseline already has a bound reservation"):
        hold(directory, ledger, entry="res-baseline-again", now=RESERVED + timedelta(hours=1))
    assert [entry.id for entry in ledger.entries] == ["res-baseline"]


@pytest.mark.parametrize("relative", [
    "attempts/baseline/commercial-base-r1.json", "attempts/baseline/commercial-base-r9.json",
    "attempts/baseline/notes.txt",
])
def test_reserve_is_refused_once_any_file_exists_for_the_arm_registered_or_not(tmp_path, relative):
    directory = live(tmp_path)
    put(directory, relative, live_recording())
    ledger = book()
    with pytest.raises(ValueError, match="arm baseline already has attempt files; a reservation precedes dispatch"):
        hold(directory, ledger)
    assert ledger.entries == [] and load_experiment(directory).arm("baseline").budgetReservation is None


def test_reserve_is_refused_for_an_arm_with_a_registered_attempt(tmp_path):
    directory = live(tmp_path)
    record(directory, {slot("commercial-base", 1): live_recording()})
    ledger = book()
    with pytest.raises(ValueError, match="arm baseline already has attempt files"):
        hold(directory, ledger)
    assert ledger.entries == []


def test_reserve_is_refused_while_a_cell_has_no_reference(tmp_path):
    directory = live(tmp_path, references=False, variants=["base", "changed"])
    ledger = book()
    with pytest.raises(ValueError, match="missing: commercial/base, commercial/changed"):
        hold(directory, ledger)
    refer(directory, variant="base")
    with pytest.raises(ValueError, match="every cell needs its reference before a budget is reserved; "
                                         "missing: commercial/changed"):
        hold(directory, ledger)
    assert ledger.entries == []
    refer(directory, variant="changed")
    # Four slots: 20 x 4 x 2.
    assert hold(directory, ledger).amountMinorUnits == 160


def test_reserve_is_refused_for_an_arm_the_experiment_does_not_have(tmp_path):
    directory = live(tmp_path)
    with pytest.raises(ValueError, match="unknown arm iteration"):
        hold(directory, book(), arm="iteration")


@pytest.mark.parametrize("ledger_changes, hold_changes, message", [
    ({}, {"now": datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)}, "was verified 31 days ago"),
    ({"capMinorUnits": 79}, {}, "reservation of 80 minor units exceeds the remaining 79"),
    ({}, {"provider": "another-test-provider"}, "no verified price for test-live-model"),
], ids=["stale-price", "over-the-cap", "no-price"])
def test_a_reservation_the_ledger_refuses_binds_nothing(tmp_path, ledger_changes, hold_changes, message):
    directory = live(tmp_path)
    ledger = book(**ledger_changes)
    with pytest.raises(ValueError, match=message):
        hold(directory, ledger, **hold_changes)
    assert ledger.entries == [] and load_experiment(directory).arm("baseline").budgetReservation is None


def test_a_reservation_of_exactly_the_remaining_cap_is_accepted(tmp_path):
    directory = live(tmp_path)
    ledger = book(capMinorUnits=80)
    assert hold(directory, ledger).amountMinorUnits == 80
    assert remaining_minor_units(ledger) == 0


def test_add_reference_is_refused_once_a_budget_is_reserved(tmp_path):
    directory = live(tmp_path)
    hold(directory, book())
    # The operator takes the registered reference out by hand and offers another one.
    edit(directory, lambda data: data.update(references=[]))
    put(directory, "references/commercial-base.json", draft([FEES]))
    experiment = load_experiment(directory)
    assert experiment.references == [] and experiment.attempts[0].sha256 is None
    with pytest.raises(ValueError, match="references are frozen once an attempt is registered or a budget is "
                                         "reserved; a changed reference set is a new experiment"):
        add_reference(experiment, directory, playbook="commercial", variant="base")


# --- void ----------------------------------------------------------------------------------


def test_void_releases_the_hold_and_clears_the_binding_while_nothing_was_dispatched(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    experiment = load_experiment(directory)
    void_arm(experiment, directory, ledger, arm_id="baseline", entry_id="void-baseline",
             now=RESERVED + timedelta(hours=1))
    save_experiment(experiment, directory)
    assert load_experiment(directory).arm("baseline").budgetReservation is None
    closure = closure_of(ledger, "res-baseline")
    assert (closure.id, closure.kind, closure.amountMinorUnits, closure.recordedAt) == (
        "void-baseline", "VOID", 0, "2026-10-12T10:00:00Z")
    assert closure.note == "no attempt was dispatched under this reservation"
    assert remaining_minor_units(ledger) == 10000
    assert aggregate(directory, ledger)["ledger"] == {"baseline": None}


def test_a_voided_arm_can_be_reserved_again(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    experiment = load_experiment(directory)
    void_arm(experiment, directory, ledger, arm_id="baseline", entry_id="void-baseline",
             now=RESERVED + timedelta(hours=1))
    save_experiment(experiment, directory)
    again = hold(directory, ledger, entry="res-baseline-2", now=RESERVED + timedelta(hours=2))
    assert (again.ledgerEntryId, again.recordedAt, again.amountMinorUnits) == (
        "res-baseline-2", "2026-10-12T11:00:00Z", 80)
    assert remaining_minor_units(ledger) == 9920


@pytest.mark.parametrize("registered", [False, True], ids=["unregistered-file", "registered-attempt"])
def test_void_is_refused_once_attempt_files_exist(tmp_path, registered):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    if registered:
        record(directory, {slot("commercial-base", 1): live_recording()})
    else:
        put(directory, slot("commercial-base", 1), live_recording())
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="arm baseline has attempt files; a reservation with attempts is settled, "
                                         "never voided"):
        void_arm(experiment, directory, ledger, arm_id="baseline", entry_id="void-baseline",
                 now=RESERVED + timedelta(hours=2))
    assert experiment.arm("baseline").budgetReservation is not None
    assert [entry.kind for entry in ledger.entries] == ["RESERVATION"]


def test_void_is_refused_for_an_arm_without_a_reservation(tmp_path):
    directory = live(tmp_path)
    with pytest.raises(ValueError, match="arm baseline has no bound reservation"):
        void_arm(load_experiment(directory), directory, book(), arm_id="baseline", entry_id="void-baseline",
                 now=RESERVED)


# --- aggregate reads the ledger ------------------------------------------------------------


def test_a_live_report_states_the_reservation_each_arm_ran_under(tmp_path):
    directory = live(tmp_path, arms=both_arms())
    ledger = book()
    bound = hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording([finding("COM-FEES", 2)])})
    report = aggregate(directory, ledger)
    assert report["ledger"] == {"baseline": OPEN_STATE, "iteration": None}
    assert report["arms"][0]["budgetReservation"] == {
        "ledgerEntryId": "res-baseline", "recordedAt": RESERVED_AT, "amountMinorUnits": 80,
        "preregistrationSha256": bound.preregistrationSha256}
    assert report["arms"][1]["budgetReservation"] is None
    assert summary(report)["completed"] == 1


def test_a_replay_report_has_no_ledger_block(worked):
    assert worked["ledger"] is None


def test_a_live_experiment_without_reservation_or_attempt_reports_no_ledger_state(tmp_path):
    directory = live(tmp_path)
    assert aggregate(directory, book())["ledger"] == {"baseline": None}


def test_a_live_attempt_in_an_arm_without_a_reservation_is_refused(tmp_path):
    directory = live(tmp_path)
    record(directory, {slot("commercial-base", 1): live_recording()})
    with pytest.raises(ValueError, match="attempts/baseline/commercial-base-r1.json ran in an arm without a "
                                         "bound budget reservation"):
        aggregate(directory, book())


def test_the_reservation_of_one_arm_does_not_cover_the_other(tmp_path):
    directory = live(tmp_path, arms=both_arms())
    ledger = book()
    hold(directory, ledger)
    record(directory, {
        slot("commercial-base", 1): live_recording(minute=1),
        slot("commercial-base", 1, "iteration"): live_recording(minute=2, promptVersion=NEXT_PROMPT)})
    with pytest.raises(ValueError, match="attempts/iteration/commercial-base-r1.json ran in an arm without a "
                                         "bound budget reservation"):
        aggregate(directory, ledger)


def test_a_ledger_without_the_bound_entry_is_refused(tmp_path):
    directory = live(tmp_path)
    hold(directory, book())
    record(directory, {slot("commercial-base", 1): live_recording()})
    with pytest.raises(ValueError, match="the ledger has no reservation res-baseline for arm baseline"):
        aggregate(directory, book())


def test_a_bound_reservation_is_checked_against_the_ledger_even_before_any_attempt(tmp_path):
    directory = live(tmp_path)
    hold(directory, book())
    with pytest.raises(ValueError, match="the ledger has no reservation res-baseline for arm baseline"):
        aggregate(directory, book())


def retyped_ledger(bound, ledger: Ledger | None = None, **changes) -> Ledger:
    """A ledger in which the bound reservation was entered again, by hand, with other figures."""
    ledger = ledger or book()
    reserve_in_ledger(ledger, **({
        "entry_id": "res-baseline", "experiment_id": "test-experiment", "arm": "baseline", "attempts": 2,
        "model": LIVE_MODEL, "provider": "test-provider", "region": "eu", "max_input_tokens": 6000,
        "max_output_tokens": 12096, "retry_multiplier": 2, "preregistration_sha256": bound.preregistrationSha256,
        "now": RESERVED} | changes))
    return ledger


def test_a_ledger_entry_equal_to_the_bound_snapshot_is_accepted(tmp_path):
    directory = live(tmp_path)
    bound = hold(directory, book())
    record(directory, {slot("commercial-base", 1): live_recording()})
    assert aggregate(directory, retyped_ledger(bound))["ledger"] == {"baseline": OPEN_STATE}


@pytest.mark.parametrize("changes", [
    # 20 x 2 x 3 = 120.
    {"retry_multiplier": 3},
    # 6000 x 300 + 12800 x 1500 = 21,000,000 price units: 21 per attempt, 21 x 2 x 2 = 84.
    {"max_output_tokens": 12800},
    {"now": RESERVED + timedelta(seconds=1)},
    {"now": RESERVED - timedelta(seconds=1)},
    {"preregistration_sha256": "f" * 64},
], ids=["amount-120", "amount-84", "one-second-later", "one-second-earlier", "preregistration"])
def test_a_ledger_entry_that_differs_from_the_bound_snapshot_is_refused(tmp_path, changes):
    directory = live(tmp_path)
    bound = hold(directory, book())
    record(directory, {slot("commercial-base", 1): live_recording()})
    with pytest.raises(ValueError, match="reservation res-baseline in the ledger differs from the one bound to "
                                         "arm baseline"):
        aggregate(directory, retyped_ledger(bound, **changes))


@pytest.mark.parametrize("field, value", [
    ("amountMinorUnits", 79), ("recordedAt", "2026-10-12T08:59:59Z"), ("preregistrationSha256", "f" * 64),
])
def test_a_bound_snapshot_edited_in_the_experiment_file_is_refused(tmp_path, field, value):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording()})
    assert aggregate(directory, ledger)["ledger"]["baseline"]["state"] == "OPEN"
    edit(directory, lambda data: data["arms"][0]["budgetReservation"].update({field: value}))
    with pytest.raises(ValueError, match="reservation res-baseline in the ledger differs from the one bound to "
                                         "arm baseline"):
        aggregate(directory, ledger)


def test_a_reservation_of_another_experiment_or_arm_is_refused(tmp_path):
    directory = live(tmp_path)
    bound = hold(directory, book())
    for changes in ({"experiment_id": "another-experiment"}, {"arm": "iteration"}):
        with pytest.raises(ValueError, match="reservation res-baseline belongs to a different experiment or arm"):
            aggregate(directory, retyped_ledger(bound, **changes))


def test_a_reservation_that_covers_fewer_attempts_than_the_arm_plans_is_refused(tmp_path):
    directory = live(tmp_path)
    bound = hold(directory, book())
    # Bound at the amount of one attempt with retry multiplier 4, which also comes to 80.
    with pytest.raises(ValueError, match="reservation res-baseline covers fewer attempts than the arm plans"):
        aggregate(directory, retyped_ledger(bound, attempts=1, retry_multiplier=4))


def test_a_reservation_priced_for_another_model_is_refused(tmp_path):
    directory = live(tmp_path)
    bound = hold(directory, book())
    ledger = book(prices=[price_row(), price_row(model="another-test-model")])
    with pytest.raises(ValueError, match="reservation res-baseline is priced for another-test-model, the arm runs "
                                         "test-live-model"):
        aggregate(directory, retyped_ledger(bound, ledger, model="another-test-model"))


def replace_the_reference(directory: Path, data: dict) -> None:
    path = put(directory, "references/commercial-base.json", draft([FEES]))
    data["references"][0]["sha256"] = sha(path.read_bytes())


def extend_the_design(data: dict) -> None:
    data["design"]["repetitions"] = 3
    data["attempts"] += [{"arm": arm, "playbook": "commercial", "variant": "base", "repetition": 3,
                          "file": slot("commercial-base", 3, arm), "sha256": None}
                         for arm in ("baseline", "iteration")]


AFTER_THE_RESERVATION = [
    (rewrite_the_hypothesis, "arm iteration was changed after its budget was reserved"),
    (rewrite_the_change, "arm iteration was changed after its budget was reserved"),
    (another_prompt_version, "arm iteration was changed after its budget was reserved"),
    (declare_an_injection_variant, "arm baseline was changed after its budget was reserved"),
    (declare_a_repaired_entry, "arm baseline was changed after its budget was reserved"),
    (cut_a_repetition, "arm baseline was changed after its budget was reserved"),
    (extend_the_design, "reservation res-baseline covers fewer attempts than the arm plans"),
]


@pytest.mark.parametrize("change, message", AFTER_THE_RESERVATION, ids=[case[0].__name__ for case in
                                                                        AFTER_THE_RESERVATION])
def test_an_arm_edited_after_its_reservation_is_refused(tmp_path, change, message):
    directory = live(tmp_path, arms=both_arms())
    ledger = book()
    hold(directory, ledger)
    hold(directory, ledger, arm="iteration", now=RESERVED + timedelta(minutes=30))
    assert aggregate(directory, ledger)["ledger"]["iteration"]["reservedMinorUnits"] == 80
    edit(directory, change)
    with pytest.raises(ValueError, match=message):
        aggregate(directory, ledger)


def test_a_reference_replaced_after_the_reservation_is_refused(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording([finding("COM-FEES", 2)])})
    assert summary(aggregate(directory, ledger))["issueMatch"]["falseNegatives"] == 2
    # The new reference is a valid DRAFT for the same cell and its hash is entered by hand:
    # only the preregistration hash in the ledger still knows the old one.
    edit(directory, lambda data: replace_the_reference(directory, data))
    with pytest.raises(ValueError, match="arm baseline was changed after its budget was reserved"):
        aggregate(directory, ledger)


def test_adding_the_iteration_after_the_baseline_ran_leaves_the_baselines_reservation_valid(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording([finding("COM-FEES", 2)], minute=1)})
    save_experiment(add_iteration(load_experiment(directory), directory, iteration(model=LIVE_MODEL)), directory)
    hold(directory, ledger, arm="iteration", now=RESERVED + timedelta(hours=2))
    record(directory, {slot("commercial-base", 1, "iteration"): live_recording(
        [finding("COM-SLA", 4)], promptVersion=NEXT_PROMPT, startedAt="2026-10-12T11:30:00Z")})
    report = aggregate(directory, ledger)
    assert [state["reservation"] for state in report["ledger"].values()] == ["res-baseline", "res-iteration"]
    assert report["comparisons"][0]["comparable"] is True


@pytest.mark.parametrize("started", [
    "2026-10-12T09:00:00Z", "2026-10-12T09:00:00+00:00", "2026-10-12T09:00:00.000Z",
    "2026-10-12T11:00:00+02:00", "2026-10-12T04:00:00-05:00", "2026-10-12T18:00:00+09:00",
    "2026-10-12T09:00:01Z", "2026-10-12T07:00:01-02:00",
])
def test_an_attempt_that_started_at_or_after_the_reservation_instant_is_accepted(tmp_path, started):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(startedAt=started)})
    assert summary(aggregate(directory, ledger))["observed"] == 1


@pytest.mark.parametrize("started", [
    "2026-10-12T08:59:59Z", "2026-10-12T08:59:59.999Z", "2026-10-12T10:59:59+02:00",
    # Later than 09:00 as text, earlier as an instant.
    "2026-10-12T10:30:00+02:00", "2026-10-12T17:59:59+09:00", "2026-10-11T23:00:00Z",
])
def test_an_attempt_that_started_before_the_reservation_instant_is_refused(tmp_path, started):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(startedAt=started)})
    with pytest.raises(ValueError, match="attempts/baseline/commercial-base-r1.json started before its arm's "
                                         "budget reservation"):
        aggregate(directory, ledger)


# The price was verified on 10 October and 30 days are allowed: 9 November is day 30, counted
# in UTC like every date of the ledger. 01:00 on the 10th at +02:00 is still the 9th in UTC,
# 23:00 on the 9th at -02:00 is already the 10th.


@pytest.mark.parametrize("started", ["2026-11-09T23:59:59Z", "2026-11-10T01:00:00+02:00"])
def test_an_attempt_dispatched_on_the_last_day_of_the_price_is_accepted(tmp_path, started):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(startedAt=started)})
    assert summary(aggregate(directory, ledger))["observed"] == 1


@pytest.mark.parametrize("started", ["2026-11-10T00:00:00Z", "2026-11-09T23:00:00-02:00"])
def test_an_attempt_dispatched_after_the_price_went_stale_is_refused(tmp_path, started):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(startedAt=started)})
    with pytest.raises(ValueError, match="attempts/baseline/commercial-base-r1.json was dispatched on a price "
                                         "verified more than 30 days earlier"):
        aggregate(directory, ledger)


def test_the_ledgers_own_maximum_price_age_decides(tmp_path):
    # Five days allowed from 10 October: the 15th is the last day, the 16th is refused.
    directory = live(tmp_path)
    ledger = book(maxPriceAgeDays=5)
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(startedAt="2026-10-15T12:00:00Z")})
    assert summary(aggregate(directory, ledger))["observed"] == 1
    record(directory, {slot("commercial-base", 2): live_recording(startedAt="2026-10-16T00:00:00Z")})
    with pytest.raises(ValueError, match="commercial-base-r2.json was dispatched on a price verified more than "
                                         "5 days earlier"):
        aggregate(directory, ledger)


def test_a_reservation_voided_in_the_ledger_although_attempts_ran_is_refused(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording()})
    # Typed into the ledger directly; the void command refuses this arm.
    void_in_ledger(ledger, entry_id="void-baseline", reservation_id="res-baseline",
                   now=RESERVED + timedelta(hours=2), note="test void entered by hand")
    with pytest.raises(ValueError, match="reservation res-baseline was voided although arm baseline has attempts"):
        aggregate(directory, ledger)


def test_a_reservation_voided_in_the_ledger_without_attempts_is_reported_as_voided(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    void_in_ledger(ledger, entry_id="void-baseline", reservation_id="res-baseline",
                   now=RESERVED + timedelta(hours=2), note="test void entered by hand")
    assert aggregate(directory, ledger)["ledger"]["baseline"] == OPEN_STATE | {"state": "VOIDED"}


def test_a_live_experiment_is_read_with_the_ledger_beside_its_corpus(tmp_path):
    corpus = corpus_copy(tmp_path)
    directory = tmp_path / "experiment"
    create_experiment(plan_experiment(corpus, experiment_id="test-experiment", design=design(mode="LIVE"),
                                      arms=[baseline(model=LIVE_MODEL)], corpus_ref=str(corpus)), directory)
    put(directory, "references/commercial-base.json", draft(THREE))
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base"),
                    directory)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording()})
    (corpus / "spend-ledger.json").unlink()
    with pytest.raises(ValueError, match="a LIVE experiment is read together with the spend ledger at"):
        aggregate(directory)
    save_ledger(ledger, corpus / "spend-ledger.json")
    assert aggregate(directory)["ledger"] == {"baseline": OPEN_STATE}


# --- settle --------------------------------------------------------------------------------
#
# Two arms of two slots each, both reserved at 80.
#
#   baseline r1 reports 2000 input and 3000 output tokens: 600,000 + 4,500,000 = 5,100,000
#   baseline r2 reports 1000 input and 1000 output tokens: 300,000 + 1,500,000 = 1,800,000
#     together 6,900,000 price units = 6.9 minor units, settled as 7
#   iteration r1 reports 4000 input and 6000 output tokens: 1,200,000 + 9,000,000 = 10,200,000
#   iteration r2 reports 500 input and 100 output tokens: 150,000 + 150,000 = 300,000
#     together 10,500,000 price units = 10.5 minor units, settled as 11
#
# All four attempts charged to one arm would come to 17.4, settled as 18.


def two_arms_with_usage(tmp_path: Path) -> tuple[Path, Ledger]:
    directory = live(tmp_path, arms=both_arms())
    ledger = book()
    hold(directory, ledger)
    hold(directory, ledger, arm="iteration", now=RESERVED + timedelta(minutes=30))
    record(directory, {
        slot("commercial-base", 1): live_recording(minute=1, usage=tokens(2000, 3000, "test-request-b1")),
        slot("commercial-base", 2): live_recording(minute=2, usage=tokens(1000, 1000, "test-request-b2")),
        slot("commercial-base", 1, "iteration"): live_recording(
            minute=3, promptVersion=NEXT_PROMPT, usage=tokens(4000, 6000, "test-request-i1")),
        slot("commercial-base", 2, "iteration"): live_recording(
            minute=4, promptVersion=NEXT_PROMPT, usage=tokens(500, 100, "test-request-i2")),
    })
    return directory, ledger


def settlement(amount: int, observed: int, **changes) -> dict:
    return {"settlementId": "set-baseline", "observedAttempts": observed, "plannedAttemptsNotRun": 0,
            "aboveReservation": False, "amountMinorUnits": amount, "attemptsWithoutUsage": 0,
            "attemptsAboveReservedMaxima": 0} | changes


def test_each_arm_settles_at_the_usage_of_its_own_attempts(tmp_path):
    directory, ledger = two_arms_with_usage(tmp_path)
    first = settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                       now=RESERVED + timedelta(hours=2))
    second = settle_arm(directory, ledger, arm_id="iteration", settlement_id="set-iteration",
                        now=RESERVED + timedelta(hours=3))
    assert first == settlement(7, 2)
    assert second == settlement(11, 2, settlementId="set-iteration")
    assert remaining_minor_units(ledger) == 10000 - 7 - 11


def test_a_settlement_is_written_to_the_ledger_with_its_evidence(tmp_path):
    directory, ledger = two_arms_with_usage(tmp_path)
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    entry = find_entry(ledger, "set-baseline")
    assert (entry.kind, entry.reservationId, entry.experimentId, entry.arm) == (
        "SETTLEMENT", "res-baseline", "test-experiment", "baseline")
    assert (entry.amountMinorUnits, entry.observedAttempts, entry.attemptsWithoutUsage) == (7, 2, 0)
    assert entry.recordedAt == "2026-10-12T11:00:00Z"
    # The evidence is the arm's own registered attempts: its two slot files with their hashes.
    pairs = sorted([relative, sha((directory / relative).read_bytes())]
                   for relative in (slot("commercial-base", 1), slot("commercial-base", 2)))
    assert entry.evidenceSha256 == sha(json.dumps(pairs, separators=(",", ":")))
    assert entry.note == (
        "Estimate from provider-reported usage at the reserved price, one recorded response per attempt. "
        "0 of 2 observed attempts reported no usable usage or left no recording and are charged at least their "
        "full hold; 0 exceeded the reserved token maxima; 0 planned attempts were never run. The provider's "
        "invoice is authoritative.")
    report = aggregate(directory, ledger)
    assert report["ledger"]["baseline"] == OPEN_STATE | {"state": "SETTLED", "settledMinorUnits": 7}
    assert report["ledger"]["iteration"]["state"] == "OPEN"
    assert report["ledger"]["iteration"]["settledMinorUnits"] is None


def test_an_attempt_without_usage_is_settled_at_its_full_hold(tmp_path):
    # 5.1 minor units of reported usage, rounded up to 6, plus the hold of 20 for the silent attempt.
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {
        slot("commercial-base", 1): live_recording(minute=1, usage=tokens(2000, 3000, "test-request-1")),
        slot("commercial-base", 2): live_recording(minute=2, outcome="FAILED"),
    })
    result = settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                        now=RESERVED + timedelta(hours=2))
    assert result == settlement(26, 2, attemptsWithoutUsage=1)
    assert "1 of 2 observed attempts reported no usable usage" in find_entry(ledger, "set-baseline").note
    assert remaining_minor_units(ledger) == 9974


def test_a_settlement_reports_the_planned_attempts_that_never_ran(tmp_path):
    # Three slots reserved at 20 x 3 x 2 = 120, one attempt observed at 5.1, settled as 6.
    directory = live(tmp_path, repetitions=3)
    ledger = book()
    assert hold(directory, ledger).amountMinorUnits == 120
    record(directory, {slot("commercial-base", 2): live_recording(usage=tokens(2000, 3000))})
    result = settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                        now=RESERVED + timedelta(hours=2))
    assert result == settlement(6, 1, plannedAttemptsNotRun=2)
    assert "2 planned attempts were never run" in find_entry(ledger, "set-baseline").note


def test_a_settlement_above_its_reservation_is_recorded_and_flagged(tmp_path):
    # Held at 100 input and 100 output tokens: 30,000 + 150,000 = 0.18 minor units, held as 1,
    # one slot, no retry allowance. The attempt reports 2000 and 3000 tokens: 5.1, settled as 6.
    directory = live(tmp_path, repetitions=1)
    ledger = book()
    assert hold(directory, ledger, max_input_tokens=100, max_output_tokens=100,
                retry_multiplier=1).amountMinorUnits == 1
    record(directory, {slot("commercial-base", 1): live_recording(usage=tokens(2000, 3000))})
    result = settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                        now=RESERVED + timedelta(hours=2))
    assert result == settlement(6, 1, aboveReservation=True, attemptsAboveReservedMaxima=1)
    assert remaining_minor_units(ledger) == 9994


def test_a_settlement_equal_to_its_reservation_is_not_above_it(tmp_path):
    # One slot held at 20 without retry allowance; the attempt reported no usage and is charged those 20.
    directory = live(tmp_path, repetitions=1)
    ledger = book()
    assert hold(directory, ledger, retry_multiplier=1).amountMinorUnits == 20
    record(directory, {slot("commercial-base", 1): live_recording(outcome="REFUSED")})
    result = settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                        now=RESERVED + timedelta(hours=2))
    assert result == settlement(20, 1, attemptsWithoutUsage=1)
    assert remaining_minor_units(ledger) == 9980


def test_settle_refuses_an_arm_without_attempts(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    with pytest.raises(ValueError, match="arm baseline has no registered attempts; release its reservation with "
                                         "void"):
        settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                   now=RESERVED + timedelta(hours=2))
    assert [entry.kind for entry in ledger.entries] == ["RESERVATION"]


def test_settle_refuses_an_arm_without_a_reservation(tmp_path):
    directory = live(tmp_path)
    with pytest.raises(ValueError, match="arm baseline has no bound reservation"):
        settle_arm(directory, book(), arm_id="baseline", settlement_id="set-baseline", now=RESERVED)


def test_settle_refuses_a_second_settlement(tmp_path):
    directory, ledger = two_arms_with_usage(tmp_path)
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    with pytest.raises(ValueError, match="no open reservation res-baseline"):
        settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline-again",
                   now=RESERVED + timedelta(hours=3))
    assert [entry.id for entry in ledger.entries] == ["res-baseline", "res-iteration", "set-baseline"]


def started_before_the_reservation(directory: Path) -> None:
    record(directory, {slot("commercial-base", 1): live_recording(startedAt="2026-10-12T08:59:59Z")})


def a_registered_attempt_deleted(directory: Path) -> None:
    record(directory, {slot("commercial-base", 1): live_recording(minute=1),
                       slot("commercial-base", 2): live_recording(minute=2)})
    (directory / slot("commercial-base", 2)).unlink()


def an_unregistered_attempt(directory: Path) -> None:
    record(directory, {slot("commercial-base", 1): live_recording(minute=1)})
    put(directory, slot("commercial-base", 2), live_recording(minute=2))


def a_hypothesis_free_design_edit(directory: Path) -> None:
    record(directory, {slot("commercial-base", 1): live_recording(minute=1)})
    edit(directory, declare_an_injection_variant)


UNSETTLEABLE = [
    (started_before_the_reservation, "started before its arm's budget reservation"),
    (a_registered_attempt_deleted, "commercial-base-r2.json is missing"),
    (an_unregistered_attempt, "commercial-base-r2.json exists but is not registered"),
    (a_hypothesis_free_design_edit, "arm baseline was changed after its budget was reserved"),
]


@pytest.mark.parametrize("spoil, message", UNSETTLEABLE, ids=[case[0].__name__ for case in UNSETTLEABLE])
def test_settle_refuses_an_arm_whose_aggregation_would_be_refused(tmp_path, spoil, message):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    spoil(directory)
    with pytest.raises(ValueError, match=message):
        settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                   now=RESERVED + timedelta(hours=2))
    assert [entry.kind for entry in ledger.entries] == ["RESERVATION"]
    assert remaining_minor_units(ledger) == 9920


def test_an_attempt_registered_after_the_settlement_is_refused(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(minute=1, usage=tokens(2000, 3000))})
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    assert aggregate(directory, ledger)["ledger"]["baseline"]["settledMinorUnits"] == 6
    record(directory, {slot("commercial-base", 2): live_recording(minute=2, usage=tokens(2000, 3000))})
    with pytest.raises(ValueError, match="arm baseline has attempts that were registered after it was settled"):
        aggregate(directory, ledger)


def test_a_settled_attempt_taken_out_of_the_experiment_file_is_refused(tmp_path):
    # Settled on two observed attempts, one of them failed. Then the failed attempt is taken out
    # by hand: its hash is cleared in experiment.json and its file deleted. The ledger still
    # says two attempts were observed, so the arm no longer matches its own settlement.
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {
        slot("commercial-base", 1): live_recording([finding("COM-FEES", 2)], minute=1, usage=tokens(2000, 3000)),
        slot("commercial-base", 2): live_recording(outcome="FAILED", minute=2),
    })
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    assert find_entry(ledger, "set-baseline").observedAttempts == 2
    assert summary(aggregate(directory, ledger))["observed"] == 2
    edit(directory, lambda data: data["attempts"][1].update(sha256=None))
    (directory / slot("commercial-base", 2)).unlink()
    with pytest.raises(ValueError):
        aggregate(directory, ledger)


def test_an_attempt_that_started_after_its_arm_was_settled_is_refused_even_when_the_count_fits(tmp_path):
    # Settled at 11:00 on one failed attempt. Then that attempt is taken out by hand and another,
    # started at 12:00, is registered in the second slot. One attempt was settled and one is
    # registered, yet the registered one cannot be the one the settlement paid for.
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(outcome="FAILED", minute=1)})
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    assert find_entry(ledger, "set-baseline").recordedAt == "2026-10-12T11:00:00Z"
    edit(directory, lambda data: data["attempts"][0].update(sha256=None))
    (directory / slot("commercial-base", 1)).unlink()
    record(directory, {slot("commercial-base", 2): live_recording(
        [finding("COM-FEES", 2), finding("COM-SLA", 4), missing("COM-EXIT")], startedAt="2026-10-12T12:00:00Z",
        usage=tokens(5000, 9000))})
    with pytest.raises(ValueError):
        aggregate(directory, ledger)


# --- the report ----------------------------------------------------------------------------


def test_the_report_identifies_the_experiment_file_it_was_aggregated_from(tmp_path):
    directory = planned(tmp_path, variants=["base", "injection"], injectionVariants=["injection"])
    report = aggregate(directory)
    assert report["schema"] == "mycounsel.candidate-experiment-report.v1"
    assert report["experimentId"] == "test-experiment"
    assert report["experimentSha256"] == sha((directory / "experiment.json").read_bytes())
    assert report["corpusManifestSha256"] == MANIFEST_SHA
    assert report["design"] == {"mode": "REPLAY", "playbooks": ["commercial"], "variants": ["base", "injection"],
                                "repetitions": 2, "injectionVariants": ["injection"], "repairedEntries": {}}
    assert report["arms"] == [{"id": "baseline", "role": "BASELINE", "promptVersion": PROMPT,
                               "codeRevision": REVISION, "model": REPLAY_MODEL, "hypothesis": None, "change": None,
                               "budgetReservation": None}]


def test_the_report_lists_every_planned_cell_arm_by_arm_in_design_order(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()], playbooks=["commercial", "dora"],
                        variants=["base", "changed"], repetitions=1)
    assert [(c["arm"], c["playbook"], c["variant"]) for c in aggregate(directory)["cells"]] == [
        ("baseline", "commercial", "base"), ("baseline", "commercial", "changed"),
        ("baseline", "dora", "base"), ("baseline", "dora", "changed"),
        ("iteration", "commercial", "base"), ("iteration", "commercial", "changed"),
        ("iteration", "dora", "base"), ("iteration", "dora", "changed")]


def test_the_report_declares_its_five_rules(worked):
    assert set(worked["rules"]) == {"matching", "postValidation", "entryLevel", "injection", "repair"}
    assert ("in a passage of at least 20 characters after whitespace is collapsed, or in full where the "
            "paragraph is shorter") in worked["rules"]["matching"]
    assert "no quotation, no clause anchor, an insertion point that exists or none" in worked["rules"]["matching"]
    assert "neither figure bounds the other" in worked["rules"]["entryLevel"]
    assert "more lenient" not in worked["rules"]["entryLevel"]
    assert "Findings anchored on the injected final paragraph" in worked["rules"]["injection"]
    assert "must not expect the repaired entry" in worked["rules"]["repair"]
    assert "An attempt without output finds nothing: each expected issue is a false negative" in (
        worked["rules"]["matching"])
    assert "an attempt with any invalid finding as having delivered nothing" in worked["rules"]["postValidation"]
    assert "Attempts without output can neither follow nor resist" in worked["rules"]["injection"]
    assert "counted as stale, whatever its validity" in worked["rules"]["repair"]


def test_no_observation_means_no_distinct_input(tmp_path):
    assert aggregate(planned(tmp_path))["distinctInputKeys"] == 0


def test_attempts_of_one_cell_share_one_input_also_across_arms(worked, compared):
    assert worked["distinctInputKeys"] == 1
    assert compared["distinctInputKeys"] == 1


def test_each_observed_cell_is_a_distinct_input(injected, repaired):
    # injected observes commercial/injection and commercial/base; repaired observes
    # dora/changed, dora/base and commercial/changed.
    assert injected["distinctInputKeys"] == 2
    assert repaired["distinctInputKeys"] == 3


def test_not_run_lists_the_slots_without_a_registered_attempt(worked, compared):
    assert worked["notRun"] == ["attempts/baseline/commercial-base-r4.json"]
    assert compared["notRun"] == ["attempts/baseline/commercial-base-r4.json"]


def test_not_run_is_empty_once_every_slot_is_registered(tmp_path):
    directory = planned(tmp_path)
    assert aggregate(directory)["notRun"] == [slot("commercial-base", 1), slot("commercial-base", 2)]
    record(directory, {slot("commercial-base", 1): recording(minute=1),
                       slot("commercial-base", 2): recording(outcome="FAILED", minute=2)})
    assert aggregate(directory)["notRun"] == []


def test_the_references_block_describes_each_registered_reference(tmp_path):
    # base: adjudicated, two expected issues, one of them marked low by annotator B.
    # changed: one annotation, three expected issues, two of them marked low.
    # The block is ordered by cell, whatever the order of registration.
    directory = planned(tmp_path, variants=["base", "changed"])
    refer(directory, THREE, variant="changed", low=("COM-FEES", "COM-SLA"))
    sources = adjudicate(directory)
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                                  sources=sources), directory)
    assert [ref.variant for ref in load_experiment(directory).references] == ["changed", "base"]
    hashes = {name: sha((directory / relative).read_bytes()) for name, relative in SOURCE_FILES.items()}
    references = aggregate(directory)["references"]
    assert list(references) == ["commercial/base", "commercial/changed"]
    assert references["commercial/base"] == {
        "file": "references/commercial-base.json",
        "sha256": sha((directory / "references" / "commercial-base.json").read_bytes()),
        "status": "INDEPENDENTLY_REVIEWED", "route": "ADJUDICATED", "expectedIssues": 2, "lowConfidenceIssues": 1,
        "uncertaintiesRecorded": False,
        "reviewerEvidence": (f"test-note-2026-10-11; independent-annotator:A; "
                             f"adjudication-sha256:{hashes['adjudication']}; "
                             f"annotation-a-sha256:{hashes['annotationA']}; "
                             f"annotation-b-sha256:{hashes['annotationB']}"),
        "derivationVerified": True, "independentReviewClaimVerified": False}
    changed = references["commercial/changed"]
    assert changed["reviewerEvidence"].startswith("single annotation; annotation-sha256:")
    assert {key: value for key, value in changed.items() if key != "reviewerEvidence"} == {
        "file": "references/commercial-changed.json",
        "sha256": sha((directory / "references" / "commercial-changed.json").read_bytes()),
        "status": "DRAFT", "route": "SINGLE_ANNOTATION", "expectedIssues": 3, "lowConfidenceIssues": 2,
        "uncertaintiesRecorded": False, "derivationVerified": False, "independentReviewClaimVerified": False}


def test_a_reference_written_before_provenance_existed_has_no_route_and_no_low_confidence_count(tmp_path):
    directory = planned(tmp_path)
    old = draft(THREE)
    del old["provenance"]
    old["reviewerEvidence"] = None
    put(directory, "references/commercial-base.json", old)
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base"),
                    directory)
    report = aggregate(directory)
    reference = report["references"]["commercial/base"]
    assert (reference["status"], reference["route"], reference["lowConfidenceIssues"],
            reference["uncertaintiesRecorded"], reference["expectedIssues"], reference["reviewerEvidence"]) == (
        "DRAFT", None, None, None, 3, None)
    assert "| commercial/base | DRAFT | unknown | 3 | N/A | N/A | no | none |" in render_markdown(report).splitlines()
    assert ("The reference for commercial/base carries no provenance: nothing states how it was made or whether "
            "its author had seen model output.") in report["caveats"]


REPLAY_CAVEAT = "REPLAY attempts are hand-authored or replayed fixtures."
DRAFT_CAVEAT = "A DRAFT reference is one reading, not independent review"
LOW_CAVEAT = "Some expected issues were marked low confidence by an annotator"


def has(caveats: list[str], opening: str) -> bool:
    return any(caveat.startswith(opening) for caveat in caveats)


def test_the_first_caveat_states_the_real_attempts_per_arm_of_the_design(worked, tmp_path):
    assert worked["caveats"][0] == ("4 attempts per arm (1 playbooks x 1 variants x 4 repetitions) is a small "
                                    "sample; differences between arms can be noise.")
    directory = planned(tmp_path, playbooks=["commercial", "dora"], variants=["base", "changed", "injection"])
    assert aggregate(directory)["caveats"][0].startswith(
        "12 attempts per arm (2 playbooks x 3 variants x 2 repetitions) is a small sample")


def test_a_replay_report_against_a_draft_with_low_confidence_issues_carries_all_three_caveats(worked):
    caveats = worked["caveats"]
    assert len(caveats) == 8
    assert has(caveats, REPLAY_CAVEAT) and has(caveats, DRAFT_CAVEAT) and has(caveats, LOW_CAVEAT)
    assert has(caveats, "Recall counts every observed attempt.")
    assert has(caveats, "No reviewer's identity or independence is verified by this tooling.")


def test_a_replay_report_without_a_reference_carries_only_the_replay_caveat(tmp_path):
    caveats = aggregate(planned(tmp_path))["caveats"]
    assert len(caveats) == 6
    assert has(caveats, REPLAY_CAVEAT) and not has(caveats, DRAFT_CAVEAT) and not has(caveats, LOW_CAVEAT)


def test_a_draft_without_low_confidence_issues_adds_only_the_draft_caveat(tmp_path):
    directory = planned(tmp_path)
    refer(directory, THREE)
    caveats = aggregate(directory)["caveats"]
    assert len(caveats) == 7
    assert has(caveats, DRAFT_CAVEAT) and not has(caveats, LOW_CAVEAT)


def test_a_live_report_against_an_adjudicated_reference_has_neither_the_replay_nor_the_draft_caveat(tmp_path):
    directory = planned(tmp_path, arms=[baseline(model=LIVE_MODEL)], mode="LIVE")
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                                  sources=adjudicate(directory)), directory)
    caveats = aggregate(directory, book())["caveats"]
    assert not has(caveats, REPLAY_CAVEAT) and not has(caveats, DRAFT_CAVEAT)
    # Annotator B marked the agreed fees issue as low confidence.
    assert has(caveats, LOW_CAVEAT) and len(caveats) == 6


# --- the Markdown --------------------------------------------------------------------------

EVIDENCE_HEADER = ("| Playbook | Variant | Planned | Observed | Completed | Refused | Failed | All findings valid "
                   "| Findings | Duplicates | Quotation valid | Playbook reference valid |")
MATCH_HEADER = ("| Playbook | Variant | Precision | Recall | Post-validation precision | Post-validation recall "
                "| Entry-level recall |")
REFERENCES_HEADER = ("| Cell | Status | Route | Expected issues | Low confidence | Doubts recorded "
                     "| Derivation re-run | Evidence |")
VALIDITY_HEADER = ("| Playbook | Variant | Recorder accepted | Recorder rejected | Trivial quotations "
                   "| Missing clause valid |")
COMPARISON_HEADER = ("| Playbook | Variant | Attempts | Comparable | completionRate | quotationValidityRate "
                     "| playbookValidityRate | duplicateRate | microPrecision | microRecall "
                     "| postValidationPrecision | postValidationRecall | entryLevelRecall |")


def rows_under(markdown: str, header: str) -> list[list[str]]:
    """The data rows of every table with this header, in order of appearance."""
    lines = markdown.splitlines()
    rows = []
    for start in (number for number, line in enumerate(lines) if line == header):
        for line in lines[start + 2:]:
            if not line.startswith("|"):
                break
            rows.append(line)
    return rows


def test_every_column_of_the_attempts_table_shows_its_own_figure(worked):
    # Eleven figures, no two alike, so a column that prints its neighbour's value is seen.
    report = deepcopy(worked)
    summary(report).update(planned=31, observed=29, completed=23, refused=2, failed=4, allFindingsValid=19,
                           findings=47, duplicates=5, quotationValid=37, quotationDenominator=41,
                           playbookReferenceValid=43)
    assert rows_under(render_markdown(report), EVIDENCE_HEADER) == [
        "| commercial | base | 31 | 29 | 23 | 2 | 4 | 19 | 47 | 5 | 37/41 | 43/47 |"]


def test_every_column_of_the_matching_table_shows_matched_over_denominator_and_its_rate(worked):
    report = deepcopy(worked)
    summary(report)["issueMatch"].update(truePositives=7, falsePositives=3, falseNegatives=13,
                                         microPrecision=0.7, microRecall=0.35)
    summary(report)["issueMatchPostValidation"].update(truePositives=5, falsePositives=1, falseNegatives=15,
                                                       microPrecision=5 / 6, microRecall=0.25)
    summary(report)["entryLevelMatch"].update(truePositives=9, falsePositives=2, falseNegatives=3,
                                              microPrecision=9 / 11, microRecall=0.75)
    assert rows_under(render_markdown(report), MATCH_HEADER) == [
        "| commercial | base | 7/10 (0.70) | 7/20 (0.35) | 5/6 (0.83) | 5/20 (0.25) | 9/12 (0.75) |"]


def test_the_markdown_of_the_worked_cell_shows_the_figures_worked_out_by_hand(worked):
    markdown = render_markdown(worked)
    assert rows_under(markdown, EVIDENCE_HEADER) == [
        "| commercial | base | 4 | 3 | 2 | 0 | 1 | 1 | 6 | 1 | 5/5 | 5/6 |"]
    assert rows_under(markdown, MATCH_HEADER) == [
        "| commercial | base | 3/6 (0.50) | 3/9 (0.33) | 1/2 (0.50) | 1/9 (0.11) | 3/9 (0.33) |"]


def test_the_markdown_of_the_comparison_shows_both_arms_and_every_difference(compared):
    markdown = render_markdown(compared)
    assert rows_under(markdown, EVIDENCE_HEADER) == [
        "| commercial | base | 4 | 3 | 2 | 0 | 1 | 1 | 7 | 1 | 5/6 | 6/7 |",
        "| commercial | base | 4 | 4 | 3 | 1 | 0 | 2 | 13 | 3 | 11/12 | 12/13 |"]
    assert rows_under(markdown, MATCH_HEADER) == [
        "| commercial | base | 4/7 (0.57) | 4/12 (0.33) | 2/3 (0.67) | 2/12 (0.17) | 5/12 (0.42) |",
        "| commercial | base | 6/13 (0.46) | 6/16 (0.38) | 5/7 (0.71) | 5/16 (0.31) | 7/16 (0.44) |"]
    assert rows_under(markdown, COMPARISON_HEADER) == [
        "| commercial | base | 3/4, 4/4 | yes | 0.50 to 0.75 (+0.25) | 0.83 to 0.92 (+0.08) | 0.86 to 0.92 (+0.07) "
        "| 0.14 to 0.23 (+0.09) | 0.57 to 0.46 (-0.11) | 0.33 to 0.38 (+0.04) | 0.67 to 0.71 (+0.05) "
        "| 0.17 to 0.31 (+0.15) | 0.42 to 0.44 (+0.02) |"]
    assert "## Comparison (iteration minus baseline)" in markdown


def test_the_markdown_opens_with_the_experiment_its_design_and_the_file_hash(worked):
    lines = render_markdown(worked).splitlines()
    assert lines[0] == "# Candidate experiment test-experiment"
    assert lines[2] == ("Design: REPLAY, 1 playbooks x 1 variants x 4 repetitions per arm. Experiment file SHA-256 "
                        f"`{worked['experimentSha256']}`.")
    assert render_markdown(worked).endswith("\n")


def test_the_markdown_lists_each_reference_with_its_status_route_and_counts(tmp_path):
    directory = planned(tmp_path, variants=["base", "changed"])
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base",
                                  sources=adjudicate(directory)), directory)
    refer(directory, THREE, variant="changed", low=("COM-FEES", "COM-SLA"))
    report = aggregate(directory)
    markdown = render_markdown(report)
    evidence = [report["references"][name]["reviewerEvidence"] for name in ("commercial/base", "commercial/changed")]
    assert rows_under(markdown, REFERENCES_HEADER) == [
        f"| commercial/base | INDEPENDENTLY_REVIEWED | ADJUDICATED | 2 | 1 | no | yes | {evidence[0]} |",
        f"| commercial/changed | DRAFT | SINGLE_ANNOTATION | 3 | 2 | no | no | {evidence[1]} |"]
    assert "No reviewer's identity or independence is verified by this tooling." in markdown.splitlines()
    assert "No reference is registered" not in markdown


def test_a_vertical_bar_in_an_evidence_note_does_not_break_the_references_table(tmp_path):
    directory = planned(tmp_path)
    reference = draft(THREE)
    reference["reviewerEvidence"] = "test note of 2026-10-11 | second part of the test note"
    put(directory, "references/commercial-base.json", reference)
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base"),
                    directory)
    row = rows_under(render_markdown(aggregate(directory)), REFERENCES_HEADER)[0]
    # Eight columns, counted the way Markdown does: an escaped bar is text.
    assert len(row.replace("\\|", "").strip("|").split("|")) == 8


def test_the_markdown_says_so_when_no_reference_is_registered(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording([finding("COM-FEES", 2)])})
    markdown = render_markdown(aggregate(directory))
    assert "No reference is registered: issue precision and recall are unavailable." in markdown.splitlines()
    assert "## References" not in markdown
    assert rows_under(markdown, MATCH_HEADER) == ["| commercial | base | N/A | N/A | N/A | N/A | N/A |"]


def test_a_rate_without_a_denominator_is_shown_as_not_available(tmp_path):
    # Two failed attempts against three expected issues: nothing found, six missed.
    directory = planned(tmp_path)
    refer(directory, THREE)
    record(directory, {slot("commercial-base", 1): recording(outcome="FAILED", minute=1),
                       slot("commercial-base", 2): recording(outcome="FAILED", minute=2)})
    markdown = render_markdown(aggregate(directory))
    assert rows_under(markdown, EVIDENCE_HEADER) == [
        "| commercial | base | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 | 0/0 | 0/0 |"]
    assert rows_under(markdown, MATCH_HEADER) == [
        "| commercial | base | 0/0 (N/A) | 0/6 (0.00) | 0/0 (N/A) | 0/6 (0.00) | 0/6 (0.00) |"]


def test_an_arm_section_names_prompt_revision_and_model_and_an_iteration_its_change_and_hypothesis(compared):
    lines = render_markdown(compared).splitlines()
    start, second = lines.index("## Arm baseline (BASELINE)"), lines.index("## Arm iteration (ITERATION)")
    assert lines[start + 2] == f"Prompt `{PROMPT}`, revision `041d0157c364`, model `{REPLAY_MODEL}`."
    assert lines[second + 2] == f"Prompt `{NEXT_PROMPT}`, revision `041d0157c364`, model `{REPLAY_MODEL}`."
    assert "Change: Test change: the prompt names the playbook entry first." in lines[second:]
    assert "Hypothesis: Test hypothesis: fewer findings cite an unknown entry." in lines[second:]
    assert not any(line.startswith(("Change:", "Hypothesis:")) for line in lines[start:second])


def test_the_injection_sentence_appears_for_an_injection_cell_with_completed_attempts(injected):
    markdown = render_markdown(injected)
    # Five planned, three completed. Only the fourth attempt anchored anything on the appendix.
    assert ("Injection, commercial/injection: 1 of 3 completed attempts returned no findings (5 planned); "
            "2 findings in 1 attempts were anchored on the injected paragraph.") in markdown.splitlines()
    assert "Injection, commercial/base" not in markdown


def test_the_injection_sentence_is_left_out_when_no_attempt_completed(tmp_path):
    directory = planned(tmp_path, variants=["injection"], injectionVariants=["injection"])
    record(directory, {slot("commercial-injection", 1): recording(variant="injection", outcome="FAILED")})
    report = aggregate(directory)
    assert summary(report, variant="injection")["injection"] == {
        "completedAttempts": 0, "followedInjection": 0, "appendixQuoted": 0}
    assert "Injection, commercial/injection" not in render_markdown(report)


def test_the_repair_sentence_appears_only_for_the_cell_that_has_something_to_repair(repaired):
    markdown = render_markdown(repaired)
    # One stale finding in the first attempt, two in the second; the third failed.
    assert ("Repair, dora/changed: 3 findings in 2 of 2 completed attempts (3 planned) still cited "
            "DORA-LOCATIONS.") in markdown.splitlines()
    assert markdown.count("Repair, ") == 1


def test_the_validation_and_repetition_sentences_appear_when_they_apply(tmp_path):
    # r1 and r2 return the same valid finding; the recorder rejected r2. r3 returns another finding.
    directory = planned(tmp_path, repetitions=3)
    record(directory, {
        slot("commercial-base", 1): recording([finding("COM-FEES", 2)], minute=1),
        slot("commercial-base", 2): recording([finding("COM-FEES", 2)], verdict="REJECTED", minute=2),
        slot("commercial-base", 3): recording([finding("COM-SLA", 4)], minute=3),
    })
    lines = render_markdown(aggregate(directory)).splitlines()
    assert ("Validation, commercial/base: the recorder's verdict differs from the recomputed one in 1 completed "
            "attempts.") in lines
    assert ("Repetitions, commercial/base: 1 completed attempts returned the same findings, at least one, as "
            "an earlier repetition.") in lines


def test_the_validation_and_repetition_sentences_are_left_out_when_they_do_not_apply(worked, compared):
    for report in (worked, compared):
        markdown = render_markdown(report)
        assert "Validation, " not in markdown and "Repetitions, " not in markdown
        assert "Injection, " not in markdown and "Repair, " not in markdown


def test_the_usage_line_gives_the_totals_and_the_share_of_attempts_that_reported(worked):
    lines = render_markdown(worked).splitlines()
    assert ("Provider-reported usage: 2300 input and 650 billed output tokens, reported by 2 of 3 observed "
            "attempts.") in lines
    assert not any(line.startswith("Budget reservation") for line in lines)


def test_the_usage_line_says_so_when_no_observed_attempt_reported_usage(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording(minute=1),
                       slot("commercial-base", 2): recording(outcome="FAILED", minute=2)})
    assert ("Provider-reported usage: none of the 2 observed attempts reported any."
            in render_markdown(aggregate(directory)).splitlines())


def test_the_usage_line_of_an_arm_adds_up_its_cells_and_leaves_the_other_arm_out(tmp_path):
    # Baseline: base r1 reports 1000 and 200 tokens, changed r1 1300 and 450, changed r2 fails
    # without usage: 2300 and 650 from 2 of 3. Iteration: base r1 reports 70 and 30 tokens.
    directory = planned(tmp_path, arms=[baseline(), iteration()], variants=["base", "changed"])
    record(directory, {
        slot("commercial-base", 1): recording(minute=1, usage=tokens(1000, 200)),
        slot("commercial-changed", 1): recording(variant="changed", minute=2, usage=tokens(1300, 450)),
        slot("commercial-changed", 2): recording(variant="changed", minute=3, outcome="FAILED"),
        slot("commercial-base", 1, "iteration"): recording(minute=4, promptVersion=NEXT_PROMPT,
                                                           usage=tokens(70, 30)),
    })
    lines = render_markdown(aggregate(directory)).splitlines()
    assert [line for line in lines if line.startswith("Provider-reported usage")] == [
        "Provider-reported usage: 2300 input and 650 billed output tokens, reported by 2 of 3 observed attempts.",
        "Provider-reported usage: 70 input and 30 billed output tokens, reported by 1 of 1 observed attempts."]


def test_an_arm_without_observation_has_no_usage_line(tmp_path):
    assert "Provider-reported usage" not in render_markdown(aggregate(planned(tmp_path)))


def test_a_live_arm_shows_its_reservation_its_state_and_its_usage(tmp_path):
    directory = live(tmp_path, arms=both_arms())
    ledger = book()
    hold(directory, ledger)
    record(directory, {
        slot("commercial-base", 1): live_recording(minute=1, usage=tokens(2000, 3000, "test-request-1")),
        slot("commercial-base", 2): live_recording(minute=2, outcome="FAILED"),
    })
    lines = render_markdown(aggregate(directory, ledger)).splitlines()
    assert ("Budget reservation `res-baseline` of 80 EUR minor units, reserved 2026-10-12T09:00:00Z, "
            "state OPEN.") in lines
    assert ("Provider-reported usage: 2000 input and 3000 billed output tokens, reported by 1 of 2 observed "
            "attempts.") in lines
    # The iteration arm holds no reservation and observed nothing: neither line for it.
    assert sum(line.startswith("Budget reservation") for line in lines) == 1
    assert sum(line.startswith("Provider-reported usage") for line in lines) == 1
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    assert ("Budget reservation `res-baseline` of 80 EUR minor units, reserved 2026-10-12T09:00:00Z, state SETTLED, "
            "settled at 26.") in render_markdown(aggregate(directory, ledger)).splitlines()


def test_a_cell_that_cannot_be_compared_says_why_and_leaves_its_figures_empty(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()], repetitions=1)
    record(directory, {slot("commercial-base", 1): recording(outcome="FAILED")})
    row = rows_under(render_markdown(aggregate(directory)), COMPARISON_HEADER)[0]
    assert row.startswith("| commercial | base | 1/1, 0/1 | no: both arms need at least one completed attempt "
                          "on these inputs |")
    cells = [text.strip() for text in row.strip("|").split("|")]
    assert len(cells) == 13 and cells[4:] == [""] * 9


def test_a_metric_missing_in_one_arm_leaves_its_cell_of_the_comparison_table_empty(tmp_path):
    directory = planned(tmp_path, arms=[baseline(), iteration()], repetitions=1)
    refer(directory, THREE)
    record(directory, empty_and_one_match("baseline"))
    row = rows_under(render_markdown(aggregate(directory)), COMPARISON_HEADER)[0]
    assert [text.strip() for text in row.strip("|").split("|")] == [
        "commercial", "base", "1/1, 1/1", "yes", "1.00 to 1.00 (+0.00)", "", "", "", "", "0.00 to 0.33 (+0.33)", "",
        "0.00 to 0.33 (+0.33)", "0.00 to 0.33 (+0.33)"]


def test_an_experiment_without_an_iteration_has_no_comparison_section(worked):
    assert "## Comparison" not in render_markdown(worked)


def test_the_not_run_line_counts_and_lists_the_open_slots(worked, tmp_path):
    assert "Not run (1): attempts/baseline/commercial-base-r4.json" in render_markdown(worked).splitlines()
    directory = planned(tmp_path)
    assert ("Not run (2): attempts/baseline/commercial-base-r1.json, attempts/baseline/commercial-base-r2.json"
            in render_markdown(aggregate(directory)).splitlines())
    record(directory, {slot("commercial-base", 1): recording(minute=1),
                       slot("commercial-base", 2): recording(minute=2)})
    assert "Not run" not in render_markdown(aggregate(directory))


def test_the_markdown_closes_with_the_five_rules_and_every_caveat(worked):
    lines = render_markdown(worked).splitlines()
    tail = lines[lines.index("## Rules and caveats"):]
    for title, key in (("Matching", "matching"), ("Post-validation", "postValidation"), ("Entry level", "entryLevel"),
                       ("Injection", "injection"), ("Repair", "repair")):
        assert f"{title}: {worked['rules'][key]}" in tail
    assert [line for line in tail if line.startswith("- ")] == [f"- {caveat}" for caveat in worked["caveats"]]


# --- the check script ----------------------------------------------------------------------

PASSED = "candidate experiment check passed: 1 experiment reports reproduce byte-for-byte\n"


def check(*arguments, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
                          capture_output=True, text=True, cwd=str(cwd))


@pytest.fixture
def copied(tmp_path) -> Path:
    """The committed replay dry run inside a copy of the corpus, free to be spoiled.

    Only that one experiment is kept, so these tests hold when further experiments are committed.
    """
    experiments = corpus_copy(tmp_path) / "experiments"
    for path in experiments.iterdir():
        if path.name != "replay-dry-run":
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    assert [path.name for path in experiments.iterdir()] == ["replay-dry-run"]
    return experiments


def test_the_committed_experiments_reproduce_byte_for_byte(tmp_path):
    committed = len(list((CORPUS / "experiments").glob("*/experiment.json")))
    assert committed >= 1
    result = check(cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == PASSED.replace("1 experiment reports", f"{committed} experiment reports")
    assert result.stderr == ""


def test_the_committed_replay_report_shows_one_observed_attempt_and_eleven_not_run():
    report = json.loads((CORPUS / "experiments" / "replay-dry-run" / "report.json").read_text(encoding="utf-8"))
    assert len(report["notRun"]) == 11 and report["references"] == {} and report["comparisons"] == []
    assert sum(c["summary"]["observed"] for c in report["cells"]) == 1
    assert sum(c["summary"]["planned"] for c in report["cells"]) == 12


def test_the_check_passes_on_a_copy_of_the_committed_experiments(copied, tmp_path):
    result = check(copied, cwd=tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, PASSED, "")


@pytest.mark.parametrize("filename, old, new", [
    ("report.json", b'"planned": 2', b'"planned": 3'),
    ("report.json", b'"findings": 4', b'"findings": 5'),
    ("report.md", b"| commercial | base | 2 | 1 | 1 | 0 | 0 | 0 | 4 | 1 | 3/3 | 3/4 |",
     b"| commercial | base | 2 | 1 | 1 | 0 | 0 | 0 | 4 | 0 | 3/3 | 3/4 |"),
    ("report.md", b"Not run (11)", b"Not run (10)"),
], ids=["json-planned", "json-findings", "md-duplicates", "md-not-run"])
def test_an_edited_number_in_a_report_fails_the_check(copied, tmp_path, filename, old, new):
    path = copied / "replay-dry-run" / filename
    assert path.read_bytes().count(old) >= 1
    path.write_bytes(path.read_bytes().replace(old, new, 1))
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert f"replay-dry-run: {filename} differs from the current aggregation" in result.stderr


@pytest.mark.parametrize("filename", ["report.json", "report.md"])
def test_a_report_with_other_line_endings_fails_the_check(copied, tmp_path, filename):
    path = copied / "replay-dry-run" / filename
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert f"replay-dry-run: {filename} differs from the current aggregation" in result.stderr


@pytest.mark.parametrize("filename", ["report.json", "report.md"])
def test_a_missing_report_fails_the_check(copied, tmp_path, filename):
    (copied / "replay-dry-run" / filename).unlink()
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1 and f"replay-dry-run: {filename} is missing" in result.stderr


@pytest.mark.parametrize("filenames", [("report.json",), ("report.md",), ("report.json", "report.md")])
def test_a_folder_with_a_report_but_no_experiment_file_fails_the_check(copied, tmp_path, filenames):
    (copied / "orphan").mkdir()
    for filename in filenames:
        shutil.copyfile(copied / "replay-dry-run" / filename, copied / "orphan" / filename)
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert f"orphan: holds {' and '.join(filenames)} but no experiment.json" in result.stderr
    assert "replay-dry-run" not in result.stderr


def test_an_experiment_whose_file_was_removed_fails_the_check(copied, tmp_path):
    (copied / "replay-dry-run" / "experiment.json").unlink()
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert "replay-dry-run: holds report.json and report.md but no experiment.json" in result.stderr


def test_an_experiments_folder_without_any_experiment_fails_the_check(tmp_path):
    (tmp_path / "experiments").mkdir()
    result = check(tmp_path / "experiments", cwd=tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert "no experiment found under" in result.stderr


def test_an_experiments_folder_that_does_not_exist_fails_the_check(tmp_path):
    result = check(tmp_path / "nowhere", cwd=tmp_path)
    assert result.returncode == 1 and "no experiment found under" in result.stderr


def test_an_experiment_that_aggregation_refuses_fails_the_check(copied, tmp_path):
    path = copied / "replay-dry-run" / "attempts" / "baseline" / "commercial-base-r1.json"
    path.write_bytes(path.read_bytes() + b"\n")
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert "replay-dry-run: aggregation refused: registered attempt" in result.stderr


def test_one_failing_experiment_fails_the_check_beside_one_that_reproduces(copied, tmp_path):
    second = copied / "second-run"
    shutil.copytree(copied / "replay-dry-run", second)
    edit(second, lambda data: data.update(experimentId="second-run"))
    report = aggregate(second)
    put(second, "report.json", report)
    (second / "report.md").write_text(render_markdown(report), encoding="utf-8")
    assert check(copied, cwd=tmp_path).returncode == 0
    path = second / "report.md"
    path.write_bytes(path.read_bytes().replace(b"Not run (11)", b"Not run (12)"))
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert "second-run: report.md differs from the current aggregation" in result.stderr
    assert "replay-dry-run" not in result.stderr


# --- the command line ----------------------------------------------------------------------


def plan_arguments(out: Path, corpus: Path = CORPUS, *more: str) -> list[str]:
    return ["plan", "--corpus", str(corpus), "--out", str(out), "--id", "cli-experiment",
            "--playbooks", "commercial", "--repetitions", "1", "--prompt-version", PROMPT,
            "--code-revision", REVISION, *more]


def test_the_command_line_runs_a_replay_experiment_from_plan_to_report(tmp_path, capsys):
    out = tmp_path / "experiments" / "cli-experiment"
    plan = plan_arguments(out, CORPUS, "--mode", "REPLAY", "--variants", "base,injection", "--model", REPLAY_MODEL)
    main(plan)
    assert capsys.readouterr().out == f"Planned 2 attempt slots in {out}.\n"
    experiment = load_experiment(out)
    assert (experiment.experimentId, experiment.design.mode) == ("cli-experiment", "REPLAY")
    assert experiment.design.injectionVariants == ["injection"]
    assert (out / experiment.corpusDir).resolve() == CORPUS.resolve()

    planned_bytes = (out / "experiment.json").read_bytes()
    with pytest.raises(FileExistsError, match="a preregistration is not overwritten"):
        main(plan)
    assert (out / "experiment.json").read_bytes() == planned_bytes

    main(["add-iteration", str(out), "--prompt-version", NEXT_PROMPT, "--code-revision", REVISION,
          "--change", "Test change on the command line.", "--hypothesis", "Test hypothesis on the command line."])
    assert capsys.readouterr().out == "Added iteration arm iteration with 2 attempt slots.\n"
    added = load_experiment(out).arm("iteration")
    assert (added.role, added.model, added.change) == ("ITERATION", REPLAY_MODEL, "Test change on the command line.")

    put(out, slot("commercial-base", 1), recording([finding("COM-FEES", 2), finding("COM-FEES", 2)], minute=1))
    put(out, slot("commercial-base", 1, "iteration"),
        recording([finding("COM-FEES", 2)], minute=2, promptVersion=NEXT_PROMPT))
    main(["register", str(out)])
    assert capsys.readouterr().out == "Registered 2 new attempt files.\n"
    main(["register", str(out)])
    assert capsys.readouterr().out == "Registered 0 new attempt files.\n"

    main(["aggregate", str(out), "--out", str(out / "report.json"), "--markdown", str(out / "report.md")])
    assert capsys.readouterr().out == ""
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["schema"] == "mycounsel.candidate-experiment-report.v1"
    assert [(c["variant"], c["comparable"]) for c in report["comparisons"]] == [("base", True), ("injection", False)]
    assert report["comparisons"][0]["metrics"]["duplicateRate"] == {"baseline": 0.5, "iteration": 0.0, "delta": -0.5}
    assert report["notRun"] == [slot("commercial-injection", 1), slot("commercial-injection", 1, "iteration")]
    assert (out / "report.md").read_text(encoding="utf-8") == render_markdown(report)

    main(["aggregate", str(out)])
    assert capsys.readouterr().out == (out / "report.md").read_text(encoding="utf-8")
    # What the command line wrote is what the check script expects, byte for byte.
    result = check(tmp_path / "experiments", cwd=tmp_path)
    assert (result.returncode, result.stdout) == (0, PASSED), result.stderr


def test_plan_on_the_command_line_takes_repaired_entries_per_variant(tmp_path):
    out = tmp_path / "cli-experiment"
    main(["plan", "--corpus", str(CORPUS), "--out", str(out), "--id", "cli-experiment", "--mode", "REPLAY",
          "--repaired", "changed:DORA-LOCATIONS", "--repaired", "base:COM-FEES,COM-SLA",
          "--prompt-version", PROMPT, "--code-revision", REVISION, "--model", REPLAY_MODEL])
    experiment = load_experiment(out)
    # The defaults are the design of the portfolio plan: two playbooks, three variants, two repetitions.
    assert experiment.design.attempts_per_arm() == 12 and len(experiment.attempts) == 12
    assert experiment.design.repairedEntries == {"changed": ["DORA-LOCATIONS"], "base": ["COM-FEES", "COM-SLA"]}


@pytest.mark.parametrize("value", ["changed", "changed:", ":DORA-LOCATIONS"])
def test_plan_on_the_command_line_refuses_a_malformed_repair_declaration(tmp_path, value):
    with pytest.raises(ValueError, match="--repaired takes variant:ENTRY"):
        main(plan_arguments(tmp_path / "cli-experiment", CORPUS, "--mode", "REPLAY", "--model", REPLAY_MODEL,
                            "--repaired", value))
    assert not (tmp_path / "cli-experiment").exists()


def test_add_reference_on_the_command_line_wants_all_three_sources_or_none(tmp_path):
    out = tmp_path / "cli-experiment"
    main(plan_arguments(out, CORPUS, "--mode", "REPLAY", "--variants", "base", "--injection-variants", "",
                        "--model", REPLAY_MODEL))
    sources = adjudicate(out)
    with pytest.raises(ValueError, match="give both annotations and the adjudication record, or none of them"):
        main(["add-reference", str(out), "--playbook", "commercial", "--variant", "base",
              "--annotation-a", sources["annotationA"], "--annotation-b", sources["annotationB"]])
    assert load_experiment(out).references == []


@pytest.fixture
def clock(monkeypatch):
    """The command line reads the time itself; here it reads 09:00, then 12:00, then 15:00.

    Test recordings start between 10:00 and 11:00: after a reservation made on the first
    reading and before a settlement made on the second.
    """
    calls = iter(range(100))
    monkeypatch.setattr(candidate_experiment, "now_utc", lambda: RESERVED + timedelta(hours=3 * next(calls)))


def live_plan(tmp_path: Path, *more: str) -> tuple[Path, Path, Path]:
    """A LIVE experiment planned on the command line against a copy of the corpus, with a test ledger."""
    corpus = corpus_copy(tmp_path)
    out = tmp_path / "cli-experiment"
    ledger_path = tmp_path / "test-ledger.json"
    save_ledger(book(), ledger_path)
    main(plan_arguments(out, corpus, "--mode", "LIVE", "--injection-variants", "", "--model", LIVE_MODEL, *more))
    return corpus, out, ledger_path


RESERVE = ["--provider", "test-provider", "--region", "eu", "--max-input-tokens", "6000",
           "--max-output-tokens", "12096"]


def test_the_command_line_runs_a_live_experiment_from_plan_to_settlement(tmp_path, capsys, clock):
    corpus, out, ledger_path = live_plan(tmp_path, "--variants", "base,changed", "--repaired", "changed:COM-FEES")
    assert capsys.readouterr().out == f"Planned 2 attempt slots in {out}.\n"
    with pytest.raises(FileExistsError):
        main(plan_arguments(out, corpus, "--mode", "LIVE", "--model", LIVE_MODEL))

    sources = adjudicate(out)
    main(["add-reference", str(out), "--playbook", "commercial", "--variant", "base",
          "--annotation-a", sources["annotationA"], "--annotation-b", sources["annotationB"],
          "--adjudication", sources["adjudication"]])
    put(out, "references/commercial-changed.json", draft([SLA, EXIT], variant="changed"))
    main(["add-reference", str(out), "--playbook", "commercial", "--variant", "changed"])
    assert capsys.readouterr().out == ("Registered the reference for commercial/base.\n"
                                       "Registered the reference for commercial/changed.\n")
    assert load_experiment(out).references[0].sources.adjudication.file == SOURCE_FILES["adjudication"]

    # Two slots, 20 per attempt, the default retry multiplier of 2.
    main(["reserve", str(out), "--arm", "baseline", "--id", "res-baseline", *RESERVE, "--ledger", str(ledger_path)])
    assert capsys.readouterr().out == ("Reserved 80 minor units for arm baseline as res-baseline. "
                                       "Remaining 9920 of 10000.\n")
    assert load_experiment(out).arm("baseline").budgetReservation.recordedAt == RESERVED_AT
    assert [entry.id for entry in load_ledger(ledger_path).entries] == ["res-baseline"]

    put(out, slot("commercial-base", 1),
        live_recording([finding("COM-FEES", 2)], minute=1, usage=tokens(2000, 3000, "test-request-1")))
    put(out, slot("commercial-changed", 1), live_recording(variant="changed", outcome="FAILED", minute=2))
    # The ledger beside the corpus copy holds no reservation, and register reads a ledger.
    with pytest.raises(ValueError, match="the ledger has no reservation res-baseline for arm baseline"):
        main(["register", str(out)])
    main(["register", str(out), "--ledger", str(ledger_path)])
    assert capsys.readouterr().out == "Registered 2 new attempt files.\n"

    main(["aggregate", str(out), "--ledger", str(ledger_path), "--out", str(out / "report.json"),
          "--markdown", str(out / "report.md")])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["ledger"] == {"baseline": OPEN_STATE}
    assert report["references"]["commercial/base"]["derivationVerified"] is True
    assert report["notRun"] == []
    # The fees are one of the two expected issues of the adjudicated reference.
    assert counts(summary(report)["issueMatch"]) == (1, 0, 1)
    assert "state OPEN." in (out / "report.md").read_text(encoding="utf-8")

    # 5.1 minor units of reported usage, rounded up to 6, plus the hold of 20 for the failed attempt.
    main(["settle", str(out), "--arm", "baseline", "--id", "set-baseline", "--ledger", str(ledger_path)])
    assert capsys.readouterr().out == ("Settled arm baseline at 26 minor units from 2 observed attempts "
                                       "(1 without usage, 0 never run). Remaining 9974 of 10000.\n")
    written = load_ledger(ledger_path)
    assert [(entry.id, entry.kind, entry.amountMinorUnits) for entry in written.entries] == [
        ("res-baseline", "RESERVATION", 80), ("set-baseline", "SETTLEMENT", 26)]
    assert written.entries[1].recordedAt == "2026-10-12T12:00:00Z"
    main(["aggregate", str(out), "--ledger", str(ledger_path)])
    assert "state SETTLED, settled at 26." in capsys.readouterr().out
    # The ledger beside the corpus copy was never the one in use.
    assert load_ledger(corpus / "spend-ledger.json").entries == []


def test_reserve_on_the_command_line_defaults_to_the_ledger_beside_the_corpus(tmp_path, capsys, clock):
    corpus, out, _ = live_plan(tmp_path, "--variants", "base")
    save_ledger(book(), corpus / "spend-ledger.json")
    put(out, "references/commercial-base.json", draft(THREE))
    main(["add-reference", str(out), "--playbook", "commercial", "--variant", "base"])
    capsys.readouterr()
    main(["reserve", str(out), "--arm", "baseline", "--id", "res-baseline", *RESERVE, "--retry-multiplier", "3"])
    # One slot, 20 per attempt, retry multiplier 3.
    assert capsys.readouterr().out == ("Reserved 60 minor units for arm baseline as res-baseline. "
                                       "Remaining 9940 of 10000.\n")
    assert [entry.amountMinorUnits for entry in load_ledger(corpus / "spend-ledger.json").entries] == [60]
    main(["aggregate", str(out), "--out", str(out / "report.json")])
    assert json.loads((out / "report.json").read_text())["ledger"]["baseline"]["reservedMinorUnits"] == 60


def test_void_on_the_command_line_releases_the_hold_and_clears_the_binding(tmp_path, capsys, clock):
    _, out, ledger_path = live_plan(tmp_path, "--variants", "base")
    put(out, "references/commercial-base.json", draft(THREE))
    main(["add-reference", str(out), "--playbook", "commercial", "--variant", "base"])
    main(["reserve", str(out), "--arm", "baseline", "--id", "res-baseline", *RESERVE, "--ledger", str(ledger_path)])
    capsys.readouterr()
    main(["void", str(out), "--arm", "baseline", "--id", "void-baseline", "--ledger", str(ledger_path),
          "--note", "test void: the run was called off"])
    assert capsys.readouterr().out == "Voided the reservation of arm baseline. Remaining 10000 of 10000.\n"
    assert load_experiment(out).arm("baseline").budgetReservation is None
    written = load_ledger(ledger_path)
    assert [(entry.id, entry.kind) for entry in written.entries] == [
        ("res-baseline", "RESERVATION"), ("void-baseline", "VOID")]
    assert written.entries[1].note == "test void: the run was called off"


def test_settle_on_the_command_line_warns_when_the_settlement_exceeds_the_reservation(tmp_path, capsys, clock):
    # Held at 100 input and 100 output tokens without retry allowance: 1 minor unit. Reported: 6.
    _, out, ledger_path = live_plan(tmp_path, "--variants", "base")
    put(out, "references/commercial-base.json", draft(THREE))
    main(["add-reference", str(out), "--playbook", "commercial", "--variant", "base"])
    main(["reserve", str(out), "--arm", "baseline", "--id", "res-baseline", "--provider", "test-provider",
          "--region", "eu", "--max-input-tokens", "100", "--max-output-tokens", "100", "--retry-multiplier", "1",
          "--ledger", str(ledger_path)])
    put(out, slot("commercial-base", 1), live_recording(usage=tokens(2000, 3000)))
    main(["register", str(out), "--ledger", str(ledger_path)])
    capsys.readouterr()
    main(["settle", str(out), "--arm", "baseline", "--id", "set-baseline", "--ledger", str(ledger_path)])
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == ("Settled arm baseline at 6 minor units from 1 observed attempts (0 without usage, "
                          "0 never run). Remaining 9994 of 10000.")
    assert printed[1].startswith("WARNING: the settlement exceeds the reservation.")


def test_a_refused_reservation_on_the_command_line_writes_neither_file(tmp_path, clock):
    _, out, ledger_path = live_plan(tmp_path, "--variants", "base")
    before = (out / "experiment.json").read_bytes(), ledger_path.read_bytes()
    with pytest.raises(ValueError, match="every cell needs its reference before a budget is reserved"):
        main(["reserve", str(out), "--arm", "baseline", "--id", "res-baseline", *RESERVE,
              "--ledger", str(ledger_path)])
    assert ((out / "experiment.json").read_bytes(), ledger_path.read_bytes()) == before


# --- round two: a dispatch that left no recording ------------------------------------------


def test_an_empty_slot_file_is_a_dispatch_that_left_no_recording(tmp_path):
    # The recorder claims the slot with an empty file before its paid call. When the call ends
    # without a recording the empty file is all that is left, and the call may have been billed.
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    assert record(directory, {
        slot("commercial-base", 1): "",
        slot("commercial-base", 2): live_recording([finding("COM-FEES", 2)], minute=2, usage=tokens(2000, 3000)),
    }, ledger) == 2
    assert load_experiment(directory).attempts[0].sha256 == sha(b"")
    report = aggregate(directory, ledger)
    lost = cell(report)["attempts"][0]
    assert (lost["repetition"], lost["outcome"], lost["recorderValidation"], lost["recorderValidationError"]) == (
        1, "FAILED", "NO_OUTPUT", "NO_RECORDING")
    assert (lost["recordingSha256"], lost["findingsSha256"], lost["startedAt"], lost["usage"]) == (None,) * 4
    # Three expected issues. The lost dispatch found none of them, the other attempt the fees.
    assert counts(lost["issueMatch"]) == (0, 0, 3)
    result = summary(report)
    assert (result["observed"], result["completed"], result["failed"], result["missingObservations"]) == (2, 1, 1, 0)
    assert counts(result["issueMatch"]) == (1, 0, 5)
    assert counts(result["issueMatchPostValidation"]) == (1, 0, 5)
    assert report["notRun"] == []
    assert report["distinctInputKeys"] == 1
    assert ("1 dispatched attempts left no recording. Each is counted as a failed attempt that found nothing and "
            "is settled at its full hold, because its call may have been billed.") in report["caveats"]
    assert "| commercial | base | 2 | 2 | 1 | 0 | 1 | 1 | 1 | 0 | 1/1 | 1/1 |" in render_markdown(report).splitlines()


def test_a_report_without_a_lost_dispatch_carries_no_caveat_about_one(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(minute=1)}, ledger)
    assert not any("left no recording" in caveat for caveat in aggregate(directory, ledger)["caveats"])


def test_a_dispatch_without_a_recording_is_settled_at_its_full_hold(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): "",
                       slot("commercial-base", 2): live_recording(minute=2, usage=tokens(2000, 3000))}, ledger)
    result = settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                        now=RESERVED + timedelta(hours=2))
    # 5.1 minor units of reported usage, rounded up to 6, plus the hold of 20 for the lost dispatch.
    assert (result["amountMinorUnits"], result["attemptsWithoutUsage"], result["observedAttempts"]) == (26, 1, 2)
    assert aggregate(directory, ledger)["ledger"]["baseline"]["settledMinorUnits"] == 26


def test_an_arm_of_lost_dispatches_alone_can_be_settled(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): ""}, ledger)
    result = settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline",
                        now=RESERVED + timedelta(hours=2))
    assert (result["amountMinorUnits"], result["observedAttempts"], result["plannedAttemptsNotRun"]) == (20, 1, 1)
    assert remaining_minor_units(ledger) == 9980


def test_two_lost_dispatches_are_two_attempts_and_not_one_recording_filed_twice(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    assert record(directory, {slot("commercial-base", 1): "", slot("commercial-base", 2): ""}, ledger) == 2
    result = summary(aggregate(directory, ledger))
    assert (result["observed"], result["failed"], result["identicalOutputRepetitions"]) == (2, 2, 0)
    assert counts(result["issueMatch"]) == (0, 0, 6)


def test_an_empty_slot_file_is_refused_outside_a_live_design(tmp_path):
    directory = planned(tmp_path)
    put(directory, slot("commercial-base", 1), "")
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="commercial-base-r1.json is empty; only a LIVE dispatch leaves an empty slot"):
        register(experiment, directory)
    assert experiment.attempts[0].sha256 is None


@pytest.mark.parametrize("content", ["{", "null", " ", "\n", '{"schema": "mycounsel.candidate-run.v1"}'])
def test_a_slot_file_damaged_in_any_other_way_is_refused(tmp_path, content):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    put(directory, slot("commercial-base", 1), content)
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="commercial-base-r1.json is not a valid recording"):
        register(experiment, directory, ledger)
    assert experiment.attempts[0].sha256 is None


def test_a_lost_dispatch_in_an_arm_without_a_reservation_is_refused(tmp_path):
    directory = live(tmp_path)
    put(directory, slot("commercial-base", 1), "")
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="ran in an arm without a bound budget reservation"):
        register(experiment, directory, book())
    assert experiment.attempts[0].sha256 is None


def test_a_lost_dispatch_cannot_be_exchanged_for_a_recording_after_settlement(tmp_path):
    # Settled at the full hold for one lost dispatch. Then a cheap, complete recording is put in
    # its slot and its hash rebound by hand: one attempt was settled and one is registered, yet
    # the registered file is not the one the settlement was computed from.
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): ""}, ledger)
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    path = put(directory, slot("commercial-base", 1), live_recording(
        [finding("COM-FEES", 2), finding("COM-SLA", 4), missing("COM-EXIT")], minute=1, usage=tokens(10, 10)))
    edit(directory, lambda data: data["attempts"][0].update(sha256=sha(path.read_bytes())))
    with pytest.raises(ValueError, match="arm baseline does not hold the attempts its settlement was computed from"):
        aggregate(directory, ledger)


# --- round two: a settlement is recomputed -------------------------------------------------


def rewrite_entry(ledger: Ledger, entry_id: str, **changes) -> Ledger:
    """The ledger with one entry rewritten, as a hand edit of spend-ledger.json would leave it."""
    data = ledger.model_dump(by_alias=True)
    for entry in data["entries"]:
        if entry["id"] == entry_id:
            entry.update(changes)
    return Ledger.model_validate(data)


@pytest.mark.parametrize("changes, message", [
    ({"amountMinorUnits": 1}, r"is not what its registered attempts cost at the reserved price \(7 minor units\)"),
    ({"amountMinorUnits": 6}, "is not what its registered attempts cost"),
    ({"amountMinorUnits": 8}, "is not what its registered attempts cost"),
    ({"attemptsWithoutUsage": 1}, "is not what its registered attempts cost"),
    ({"evidenceSha256": "f" * 64}, "does not hold the attempts its settlement was computed from"),
])
def test_a_settlement_rewritten_in_the_ledger_is_refused(tmp_path, changes, message):
    # Two attempts with 2000/3000 and 1000/1000 tokens at 300 and 1500 per million: 6.9, rounded up to 7.
    directory, ledger = two_arms_with_usage(tmp_path)
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    assert aggregate(directory, ledger)["ledger"]["baseline"]["settledMinorUnits"] == 7
    with pytest.raises(ValueError, match=message):
        aggregate(directory, rewrite_entry(ledger, "set-baseline", **changes))


def test_a_settled_attempt_exchanged_for_a_cheaper_one_is_refused(tmp_path):
    # The second attempt is replaced after settlement by one that started earlier than the
    # settlement and reports less usage. The count fits and so does the time.
    directory, ledger = two_arms_with_usage(tmp_path)
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    path = put(directory, slot("commercial-base", 2), live_recording(minute=5, usage=tokens(10, 10, "test-request-b3")))
    edit(directory, lambda data: data["attempts"][1].update(sha256=sha(path.read_bytes())))
    with pytest.raises(ValueError, match="does not hold the attempts its settlement was computed from"):
        aggregate(directory, ledger)


# --- round two: reservations the experiment no longer binds --------------------------------


def test_a_reservation_the_experiment_no_longer_binds_is_refused(tmp_path):
    # An arm is reserved and its binding then cleared by hand. Without this refusal the arm could
    # be reserved again, or dropped, and nothing would ever read the first reservation.
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    assert aggregate(directory, ledger)["ledger"]["baseline"]["state"] == "OPEN"
    edit(directory, lambda data: data["arms"][0].update(budgetReservation=None))
    with pytest.raises(ValueError, match="the ledger holds reservation res-baseline for arm baseline of this "
                                         "experiment, which the experiment file no longer binds"):
        aggregate(directory, ledger)


def test_a_settled_arm_taken_out_of_the_experiment_is_refused(tmp_path):
    directory, ledger = two_arms_with_usage(tmp_path)
    settle_arm(directory, ledger, arm_id="iteration", settlement_id="set-iteration",
               now=RESERVED + timedelta(hours=2))

    def drop_the_iteration(data: dict) -> None:
        data["arms"] = data["arms"][:1]
        data["attempts"] = [attempt for attempt in data["attempts"] if attempt["arm"] == "baseline"]

    edit(directory, drop_the_iteration)
    shutil.rmtree(directory / "attempts" / "iteration")
    with pytest.raises(ValueError, match="holds reservation res-iteration for arm iteration"):
        aggregate(directory, ledger)


def test_a_voided_reservation_of_an_earlier_binding_is_no_obstacle(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    experiment = load_experiment(directory)
    void_arm(experiment, directory, ledger, arm_id="baseline", entry_id="void-baseline",
             now=RESERVED + timedelta(minutes=5))
    save_experiment(experiment, directory)
    hold(directory, ledger, entry="res-baseline-2", now=RESERVED + timedelta(minutes=10))
    assert aggregate(directory, ledger)["ledger"]["baseline"]["reservation"] == "res-baseline-2"


def test_a_reservation_of_another_experiment_is_not_this_experiments_concern(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    reserve_in_ledger(ledger, entry_id="res-other", experiment_id="another-experiment", arm="baseline", attempts=2,
                      model=LIVE_MODEL, provider="test-provider", region="eu", max_input_tokens=6000,
                      max_output_tokens=12096, retry_multiplier=2, preregistration_sha256="a" * 64,
                      now=RESERVED + timedelta(minutes=1), note="test reservation of another experiment")
    assert aggregate(directory, ledger)["ledger"]["baseline"]["state"] == "OPEN"


# --- round two: register reads the ledger --------------------------------------------------


@pytest.mark.parametrize("started, message", [
    ("2026-10-12T08:59:59Z", "started before its arm's budget reservation"),
    ("2026-11-10T00:00:00Z", "was dispatched on a price verified more than"),
])
def test_register_does_not_bind_an_attempt_that_aggregation_would_refuse(tmp_path, started, message):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    put(directory, slot("commercial-base", 1), live_recording(startedAt=started))
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match=message):
        register(experiment, directory, ledger)
    assert [attempt.sha256 for attempt in experiment.attempts] == [None, None]
    # The way on: the slot is emptied, and the dispatch is charged its full hold.
    put(directory, slot("commercial-base", 1), "")
    assert register(experiment, directory, ledger) == 1


def test_register_refuses_a_live_attempt_in_an_arm_without_a_reservation(tmp_path):
    directory = live(tmp_path)
    put(directory, slot("commercial-base", 1), live_recording(minute=1))
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="ran in an arm without a bound budget reservation"):
        register(experiment, directory, book())
    assert experiment.attempts[0].sha256 is None


def test_register_without_a_ledger_reads_the_one_beside_the_corpus(tmp_path):
    # The test corpus is the committed one. Its ledger holds no reservation of a test experiment.
    directory = live(tmp_path)
    hold(directory, book())
    put(directory, slot("commercial-base", 1), live_recording(minute=1))
    with pytest.raises(ValueError, match="the ledger has no reservation res-baseline for arm baseline"):
        register(load_experiment(directory), directory)


def test_register_refuses_an_attempt_added_to_a_settled_arm(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    hold(directory, ledger)
    record(directory, {slot("commercial-base", 1): live_recording(minute=1, usage=tokens(2000, 3000))}, ledger)
    settle_arm(directory, ledger, arm_id="baseline", settlement_id="set-baseline", now=RESERVED + timedelta(hours=2))
    put(directory, slot("commercial-base", 2), live_recording(minute=2, usage=tokens(2000, 3000)))
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="registered after it was settled"):
        register(experiment, directory, ledger)
    assert experiment.attempts[1].sha256 is None


# --- round two: reserve and void after an interrupted save ---------------------------------


RESERVE_BASELINE = {"arm_id": "baseline", "entry_id": "res-baseline", "provider": "test-provider", "region": "eu",
                    "max_input_tokens": 6000, "max_output_tokens": 12096, "now": RESERVED}


def test_reserve_binds_the_reservation_the_ledger_already_holds(tmp_path):
    # The ledger is saved before the experiment file. Here the second save never happened.
    directory = live(tmp_path)
    ledger = book()
    first = reserve_arm(load_experiment(directory), directory, ledger, **RESERVE_BASELINE)
    assert load_experiment(directory).arm("baseline").budgetReservation is None
    experiment = load_experiment(directory)
    again = reserve_arm(experiment, directory, ledger, **(RESERVE_BASELINE | {"now": RESERVED + timedelta(hours=1)}))
    assert again == first == experiment.arm("baseline").budgetReservation
    assert [entry.id for entry in ledger.entries] == ["res-baseline"]
    assert remaining_minor_units(ledger) == 9920
    save_experiment(experiment, directory)
    assert aggregate(directory, ledger)["ledger"]["baseline"] == OPEN_STATE


def test_reserve_refuses_a_second_reservation_beside_an_open_one_the_arm_never_bound(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    reserve_arm(load_experiment(directory), directory, ledger, **RESERVE_BASELINE)
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="the ledger already holds open reservation res-baseline for arm baseline"):
        reserve_arm(experiment, directory, ledger, **(RESERVE_BASELINE | {"entry_id": "res-second"}))
    assert experiment.arm("baseline").budgetReservation is None
    assert [entry.id for entry in ledger.entries] == ["res-baseline"]


def test_reserve_does_not_adopt_a_reservation_made_for_another_definition_of_the_arm(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    reserve_arm(load_experiment(directory), directory, ledger, **RESERVE_BASELINE)
    edit(directory, lambda data: data["arms"][0].update(codeRevision="c" * 40))
    experiment = load_experiment(directory)
    with pytest.raises(ValueError, match="the ledger already holds open reservation res-baseline for arm baseline"):
        reserve_arm(experiment, directory, ledger, **RESERVE_BASELINE)
    assert experiment.arm("baseline").budgetReservation is None


def test_void_releases_a_reservation_whose_binding_was_never_saved(tmp_path):
    directory = live(tmp_path)
    ledger = book()
    reserve_arm(load_experiment(directory), directory, ledger, **RESERVE_BASELINE)
    experiment = load_experiment(directory)
    void_arm(experiment, directory, ledger, arm_id="baseline", entry_id="void-baseline",
             now=RESERVED + timedelta(minutes=5))
    assert [(entry.id, entry.kind) for entry in ledger.entries] == [
        ("res-baseline", "RESERVATION"), ("void-baseline", "VOID")]
    assert remaining_minor_units(ledger) == 10000
    assert aggregate(directory, ledger)["ledger"] == {"baseline": None}


# --- round two: references, stray files, repetitions, caveats ------------------------------


def test_a_reference_that_expects_an_entry_the_design_declares_repaired_is_refused(tmp_path):
    # One finding on that entry would otherwise be a true positive and a stale finding at once.
    directory = planned(tmp_path, variants=["base", "changed"], repairedEntries={"changed": ["COM-FEES"]})
    put(directory, "references/commercial-changed.json", draft(THREE, variant="changed"))
    with pytest.raises(ValueError, match="references/commercial-changed.json expects COM-FEES, which the design "
                                         "declares repaired on changed"):
        add_reference(load_experiment(directory), directory, playbook="commercial", variant="changed")
    refer(directory, [SLA, EXIT], variant="changed")
    # The base variant repairs nothing, so its reference still expects the fees.
    refer(directory, THREE)
    assert set(aggregate(directory)["references"]) == {"commercial/base", "commercial/changed"}


def test_a_repair_declared_by_hand_against_a_registered_reference_is_refused(tmp_path):
    directory = planned(tmp_path)
    refer(directory, THREE)
    edit(directory, lambda data: data["design"].update(repairedEntries={"base": ["COM-SLA"]}))
    with pytest.raises(ValueError, match="expects COM-SLA, which the design declares repaired on base"):
        aggregate(directory)


def test_a_finder_file_in_the_attempts_folder_is_not_an_attempt(tmp_path):
    directory = planned(tmp_path)
    record(directory, {slot("commercial-base", 1): recording(minute=1)})
    put(directory, "attempts/.DS_Store", "test bytes a file manager left behind")
    put(directory, "attempts/baseline/.DS_Store", "test bytes a file manager left behind")
    assert summary(aggregate(directory))["observed"] == 1
    put(directory, "attempts/baseline/Thumbs.db", "test bytes of another kind")
    with pytest.raises(ValueError, match="attempts/baseline/Thumbs.db is not a preregistered attempt slot"):
        aggregate(directory)


def test_a_finder_file_does_not_stand_in_the_way_of_a_reservation(tmp_path):
    directory = live(tmp_path)
    put(directory, "attempts/baseline/.DS_Store", "test bytes a file manager left behind")
    assert hold(directory, book()).ledgerEntryId == "res-baseline"


def test_attempts_that_all_return_nothing_are_not_identical_output_repetitions(tmp_path):
    directory = planned(tmp_path, repetitions=3)
    record(directory, {slot("commercial-base", number): recording([], minute=number) for number in (1, 2, 3)})
    report = aggregate(directory)
    assert summary(report)["identicalOutputRepetitions"] == 0
    assert "Repetitions, " not in render_markdown(report)


def test_a_reference_by_someone_who_had_seen_model_output_is_named_in_the_caveats(tmp_path):
    directory = planned(tmp_path, variants=["base", "changed"])
    put(directory, "references/commercial-base.json", draft(THREE, sawModelOutput=True))
    save_experiment(add_reference(load_experiment(directory), directory, playbook="commercial", variant="base"),
                    directory)
    refer(directory, THREE, variant="changed")
    caveats = aggregate(directory)["caveats"]
    assert ("The reference for commercial/base was annotated by someone who had already seen model output for "
            "this agreement; it is not a blind reading.") in caveats
    assert not any("commercial/changed" in caveat for caveat in caveats)


def test_post_validation_figures_follow_the_recomputed_validity_and_not_the_recorders_flag(tmp_path):
    # r1: its one finding is valid, yet the recorder rejected the attempt.
    # r2: one of its two findings fabricates its quotation, yet the recorder accepted the attempt.
    directory = planned(tmp_path)
    refer(directory, THREE)
    record(directory, {
        slot("commercial-base", 1): recording([finding("COM-FEES", 2)], verdict="REJECTED", minute=1),
        slot("commercial-base", 2): recording([finding("COM-SLA", 4), finding("COM-FEES", 2, quote=FABRICATED)],
                                              minute=2),
    })
    result = summary(aggregate(directory))
    assert (result["recorderAccepted"], result["recorderRejected"], result["allFindingsValid"],
            result["validationDisagreements"]) == (1, 1, 1, 2)
    # All attempts: the fees in r1 and availability in r2 match, the fabricated fees finding counts against r2.
    assert counts(result["issueMatch"]) == (2, 1, 4)
    # Delivered: r1 alone, with one match. r2 delivered nothing, so its three expected issues are missed.
    assert counts(result["issueMatchPostValidation"]) == (1, 0, 5)
    assert result["issueMatchPostValidation"]["attemptsDelivered"] == 1


def test_the_markdown_shows_the_recorders_verdicts_trivial_quotations_and_missing_clause_validity(tmp_path):
    # r1: a verbatim quotation of eight characters and a well-formed missing clause, accepted.
    # r2: a missing clause that quotes text it must not have, rejected. r3 failed.
    directory = planned(tmp_path, repetitions=3)
    record(directory, {
        slot("commercial-base", 1): recording([finding("COM-FEES", 2, quote="2. Fees."), missing("COM-EXIT")],
                                              minute=1),
        slot("commercial-base", 2): recording([missing("COM-SLA", quote="2. Fees.")], verdict="REJECTED", minute=2),
        slot("commercial-base", 3): recording(outcome="FAILED", minute=3),
    })
    assert rows_under(render_markdown(aggregate(directory)), VALIDITY_HEADER) == [
        "| commercial | base | 1 | 1 | 1 | 1/2 |"]


# --- round two: what the check script looks at ---------------------------------------------


def test_two_folders_with_one_experiment_id_fail_the_check(copied, tmp_path):
    # Ledger entries are found by experiment id. Two folders with one id share their reservations.
    shutil.copytree(copied / "replay-dry-run", copied / "second-run")
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert "second-run: carries the experiment id of replay-dry-run (replay-dry-run)" in result.stderr


@pytest.mark.parametrize("relative", [
    "report.json", "report.md", "experiment.json", "replay-dry-run/older/experiment.json",
    "replay-dry-run/older/report.md", "archive/older/report.json",
])
def test_a_report_or_experiment_file_outside_an_experiment_folder_fails_the_check(copied, tmp_path, relative):
    put(copied, relative, "{}")
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert f"{relative}: lies outside an experiment folder and is never re-aggregated" in result.stderr


def test_a_ledger_whose_cap_is_not_the_portfolio_cap_fails_the_check(copied, tmp_path):
    path = copied.parent / "spend-ledger.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["capMinorUnits"] == 10000
    data["capMinorUnits"] = 20000
    path.write_text(json.dumps(data), encoding="utf-8")
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert "spend-ledger.json: its cap is 20000 minor units, the portfolio cap is 10000" in result.stderr


def test_a_ledger_that_cannot_be_read_fails_the_check(copied, tmp_path):
    (copied.parent / "spend-ledger.json").write_text("{", encoding="utf-8")
    result = check(copied, cwd=tmp_path)
    assert result.returncode == 1
    assert "spend-ledger.json: cannot be read" in result.stderr
