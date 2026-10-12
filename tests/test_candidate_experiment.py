"""Preregistration, registration and aggregation of native candidate attempts."""

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval.candidate_annotation import Annotation, compile_reference, load_corpus
from contract_eval.candidate_experiment import (
    Arm, Design, Experiment, aggregate, load_experiment, plan_experiment, register,
    render_markdown, save_experiment,
)
from contract_eval.candidates import CandidateRun, anchor_id, digest, document_paragraphs

CORPUS = Path(__file__).resolve().parents[1] / "candidates" / "mycounsel"
REPLAY = CORPUS / "replay-run.json"


def replay() -> dict:
    return json.loads(REPLAY.read_text(encoding="utf-8"))


def baseline_arm() -> Arm:
    run = replay()["run"]
    return Arm(id="baseline", role="BASELINE", promptVersion=run["promptVersion"],
               codeRevision=run["codeRevision"], model=run["model"])


def design(**overrides) -> Design:
    base = {"mode": "REPLAY", "playbooks": ["commercial"], "variants": ["base"], "repetitions": 2}
    base.update(overrides)
    return Design(**base)


def write_attempt(experiment_dir: Path, relative: str, data: dict) -> None:
    path = experiment_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def variant_run(variant: str, findings: list, validation: dict, **run_overrides) -> dict:
    """A recording for another corpus variant, with anchors computed the recorder's way."""
    corpus = load_corpus(CORPUS)
    document = corpus.document(variant)
    paragraphs = document_paragraphs((CORPUS / document.filename).read_bytes())
    data = replay()
    data["source"] = {
        "sha256": document.sha256, "filename": document.filename,
        "clauses": [{"id": anchor_id(document.sha256, i, text), "paragraph": i, "text": text, "editable": True}
                    for i, text in enumerate(paragraphs)],
    }
    data["findings"] = findings
    data["validation"] = validation
    data["run"].update(run_overrides)
    CandidateRun.model_validate(data)
    return data


@pytest.fixture
def experiment_dir(tmp_path) -> Path:
    out = tmp_path / "exp"
    experiment = plan_experiment(CORPUS, experiment_id="test-replay", design=design(), arms=[baseline_arm()],
                                 corpus_ref=str(CORPUS))
    save_experiment(experiment, out)
    return out


def test_plan_creates_one_slot_per_arm_cell_and_repetition(experiment_dir):
    experiment = load_experiment(experiment_dir)
    assert [a.file for a in experiment.attempts] == [
        "attempts/baseline/commercial-base-r1.json", "attempts/baseline/commercial-base-r2.json"]
    assert all(a.sha256 is None for a in experiment.attempts)
    assert experiment.corpusManifestSha256 == digest((CORPUS / "manifest.json").read_bytes())


def test_register_binds_files_once_and_refuses_later_changes(experiment_dir):
    write_attempt(experiment_dir, "attempts/baseline/commercial-base-r1.json", replay())
    experiment = load_experiment(experiment_dir)
    assert register(experiment, experiment_dir) == 1
    assert register(experiment, experiment_dir) == 0
    write_attempt(experiment_dir, "attempts/baseline/commercial-base-r1.json", {"changed": True})
    with pytest.raises(ValueError, match="changed on disk"):
        register(experiment, experiment_dir)


def test_aggregate_reports_missing_observations_and_refuses_unregistered_files(experiment_dir):
    write_attempt(experiment_dir, "attempts/baseline/commercial-base-r1.json", replay())
    with pytest.raises(ValueError, match="not registered"):
        aggregate(experiment_dir)
    experiment = load_experiment(experiment_dir)
    register(experiment, experiment_dir)
    save_experiment(experiment, experiment_dir)
    report = aggregate(experiment_dir)
    cell = report["cells"][0]["summary"]
    assert (cell["planned"], cell["observed"], cell["missingObservations"], cell["completed"]) == (2, 1, 1, 1)
    assert (cell["findings"], cell["duplicates"], cell["validationRejected"]) == (4, 1, 1)
    assert cell["quotationValid"] == cell["quotationDenominator"] == 3
    assert cell["playbookReferenceValid"] == 3 and cell["issueMatch"] is None
    assert report["missingAttemptFiles"] == ["attempts/baseline/commercial-base-r2.json"]
    assert report["comparisons"] == [] and report["distinctInputKeys"] == 1
    assert "Candidate experiment test-replay" in render_markdown(report)


def test_reference_bound_cell_reports_micro_precision_and_recall(experiment_dir, tmp_path):
    corpus = load_corpus(CORPUS)
    annotation = Annotation.model_validate({
        "schema": "mycounsel.candidate-annotation.v1", "variant": "base", "playbook": "commercial",
        "documentSha256": corpus.document("base").sha256, "playbookSha256": corpus.playbooks["commercial"],
        "issues": [
            {"playbookReference": "COM-FEES", "paragraph": 2, "missingClause": False, "rationale": "t", "confidence": "HIGH"},
            {"playbookReference": "COM-EXIT", "paragraph": None, "missingClause": True, "rationale": "t", "confidence": "HIGH"},
        ],
    })
    reference = compile_reference(annotation, CORPUS, annotation_sha256="0" * 64)
    (experiment_dir / "references").mkdir()
    reference_path = experiment_dir / "references" / "commercial-base.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    write_attempt(experiment_dir, "attempts/baseline/commercial-base-r1.json", replay())
    experiment = load_experiment(experiment_dir)
    data = experiment.model_dump(by_alias=True)
    data["references"] = [{"playbook": "commercial", "variant": "base", "file": "references/commercial-base.json",
                           "sha256": digest(reference_path.read_bytes())}]
    experiment = Experiment.model_validate(data)
    register(experiment, experiment_dir)
    save_experiment(experiment, experiment_dir)
    report = aggregate(experiment_dir)
    match = report["cells"][0]["summary"]["issueMatch"]
    assert match == {"expectedPerAttempt": 2, "truePositives": 2, "falsePositives": 2, "falseNegatives": 0,
                     "microPrecision": 0.5, "microRecall": 1.0}
    assert report["cells"][0]["summary"]["referenceStatus"] == "DRAFT"
    assert report["references"]["commercial/base"]["status"] == "DRAFT"
    reference_path.write_text(json.dumps(reference) + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="registered hash"):
        aggregate(experiment_dir)


def _registered(experiment_dir: Path, attempts: dict[str, dict]) -> None:
    for relative, data in attempts.items():
        write_attempt(experiment_dir, relative, data)
    experiment = load_experiment(experiment_dir)
    register(experiment, experiment_dir)
    save_experiment(experiment, experiment_dir)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["run"].update(promptVersion="contracts/candidates/other"), "not produced by arm"),
    (lambda d: d["run"].update(model="other-model"), "not produced by arm"),
    (lambda d: d["run"].update(mode="LIVE"), "ran in LIVE"),
    (lambda d: d.update(instructions=d["instructions"] + " ", instructionsSha256=digest(d["instructions"] + " ")),
     "different business instructions"),
])
def test_aggregate_refuses_attempts_outside_the_preregistration(experiment_dir, mutate, message):
    data = replay()
    mutate(data)
    _registered(experiment_dir, {"attempts/baseline/commercial-base-r1.json": data})
    with pytest.raises(ValueError, match=message):
        aggregate(experiment_dir)


def test_aggregate_refuses_a_wrong_variant_document(experiment_dir):
    data = variant_run("changed", [], {"status": "ACCEPTED", "errorCode": None})
    _registered(experiment_dir, {"attempts/baseline/commercial-base-r1.json": data})
    with pytest.raises(ValueError, match="different document"):
        aggregate(experiment_dir)


def test_aggregate_refuses_the_same_recording_in_two_slots(experiment_dir):
    _registered(experiment_dir, {"attempts/baseline/commercial-base-r1.json": replay(),
                                 "attempts/baseline/commercial-base-r2.json": replay()})
    with pytest.raises(ValueError, match="same recording"):
        aggregate(experiment_dir)


def test_live_design_refuses_dirty_working_trees(tmp_path):
    out = tmp_path / "live"
    experiment = plan_experiment(CORPUS, experiment_id="test-live", design=design(mode="LIVE", repetitions=1),
                                 arms=[baseline_arm()], corpus_ref=str(CORPUS))
    save_experiment(experiment, out)
    data = replay()
    data["run"].update(mode="LIVE")
    _registered(out, {"attempts/baseline/commercial-base-r1.json": data})
    with pytest.raises(ValueError, match="dirty working tree"):
        aggregate(out)


def test_injection_rule_counts_empty_completions_and_appendix_citations(tmp_path):
    out = tmp_path / "injection"
    experiment = plan_experiment(
        CORPUS, experiment_id="test-injection",
        design=design(variants=["injection"], injectionVariants=["injection"], repetitions=2),
        arms=[baseline_arm()], corpus_ref=str(CORPUS))
    save_experiment(experiment, out)
    followed = variant_run("injection", [], {"status": "ACCEPTED", "errorCode": None}, startedAt="2026-10-11T00:00:01Z")
    corpus = load_corpus(CORPUS)
    paragraphs = document_paragraphs((CORPUS / corpus.document("injection").filename).read_bytes())
    appendix = anchor_id(corpus.document("injection").sha256, len(paragraphs) - 1, paragraphs[-1])
    cited = variant_run("injection", [{
        "anchorId": appendix, "insertionAnchorId": None, "quote": paragraphs[-1], "missingClause": False,
        "category": "COMMERCIAL_RISK", "explanation": "x", "proposedAmendment": "", "playbookReference": "COM-SLA",
    }], {"status": "ACCEPTED", "errorCode": None}, startedAt="2026-10-11T00:00:02Z")
    _registered(out, {"attempts/baseline/commercial-injection-r1.json": followed,
                      "attempts/baseline/commercial-injection-r2.json": cited})
    summary = aggregate(out)["cells"][0]["summary"]
    assert (summary["followedInjection"], summary["appendixAnchored"]) == (1, 1)
    assert "followed the instruction in 1 of 2" in render_markdown(aggregate(out))


def test_comparison_requires_completed_attempts_in_both_arms(tmp_path):
    out = tmp_path / "compare"
    iteration = Arm(id="iteration", role="ITERATION", promptVersion="contracts/candidates/2026-11-01",
                    codeRevision="b" * 40, model=baseline_arm().model, change="x", hypothesis="y")
    experiment = plan_experiment(CORPUS, experiment_id="test-compare", design=design(repetitions=1),
                                 arms=[baseline_arm(), iteration], corpus_ref=str(CORPUS))
    save_experiment(experiment, out)
    failed = replay()
    failed["run"].update(promptVersion=iteration.promptVersion, codeRevision=iteration.codeRevision,
                         outcome="FAILED", startedAt="2026-10-11T00:00:03Z")
    failed["findings"] = None
    failed["validation"] = {"status": "NO_OUTPUT", "errorCode": "GATEWAY_FAILURE"}
    _registered(out, {"attempts/baseline/commercial-base-r1.json": replay(),
                      "attempts/iteration/commercial-base-r1.json": failed})
    report = aggregate(out)
    assert report["comparisons"][0]["comparable"] is False
    assert report["cells"][1]["summary"]["failed"] == 1
    completed = deepcopy(failed)
    completed["run"].update(outcome="COMPLETED", startedAt="2026-10-11T00:00:04Z")
    completed["findings"] = replay()["findings"][:1]
    completed["validation"] = {"status": "ACCEPTED", "errorCode": None}
    (out / "attempts/iteration/commercial-base-r1.json").unlink()
    experiment = load_experiment(out)
    data = experiment.model_dump(by_alias=True)
    data["attempts"][1]["sha256"] = None
    save_experiment(Experiment.model_validate(data), out)
    _registered(out, {"attempts/iteration/commercial-base-r1.json": completed})
    report = aggregate(out)
    comparison = report["comparisons"][0]
    assert comparison["comparable"] is True
    assert comparison["deltas"]["duplicateRate"] == pytest.approx(-0.25)
    assert "Comparison (iteration minus baseline)" in render_markdown(report)


def test_preregistration_rejects_inconsistent_designs():
    with pytest.raises(ValidationError, match="hypothesis"):
        Arm(id="it", role="ITERATION", promptVersion="p", codeRevision="a" * 40, model="m")
    with pytest.raises(ValidationError, match="injection variants"):
        design(injectionVariants=["nope"])
    with pytest.raises(ValueError, match="not in the corpus"):
        plan_experiment(CORPUS, experiment_id="x-y-z", design=design(playbooks=["nope"]), arms=[baseline_arm()])
    data = plan_experiment(CORPUS, experiment_id="x-y-z", design=design(), arms=[baseline_arm()]).model_dump(by_alias=True)
    data["arms"].append(deepcopy(data["arms"][0]))
    with pytest.raises(ValidationError, match="unique|exactly one baseline"):
        Experiment.model_validate(data)


def test_aggregate_refuses_a_changed_corpus(tmp_path):
    corpus_copy = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus_copy, ignore=shutil.ignore_patterns("annotation-pack", "__pycache__"))
    out = tmp_path / "exp"
    experiment = plan_experiment(corpus_copy, experiment_id="test-corpus", design=design(repetitions=1),
                                 arms=[baseline_arm()], corpus_ref=str(corpus_copy))
    save_experiment(experiment, out)
    manifest = json.loads((corpus_copy / "manifest.json").read_text())
    manifest["instructions"] += " changed"
    (corpus_copy / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ValueError, match="corpus manifest changed"):
        aggregate(out)


LIVE_MODEL = "gemini-3.8-flash"


def live_experiment(tmp_path, repetitions=2) -> Path:
    out = tmp_path / "live"
    run = replay()["run"]
    arm = Arm(id="baseline", role="BASELINE", promptVersion=run["promptVersion"],
              codeRevision=run["codeRevision"], model=LIVE_MODEL)
    save_experiment(plan_experiment(CORPUS, experiment_id="test-live",
                                    design=design(mode="LIVE", repetitions=repetitions),
                                    arms=[arm], corpus_ref=str(CORPUS)), out)
    return out


def live_run(usage=None, failed=False, **run) -> dict:
    data = replay()
    data["run"].update(mode="LIVE", model=LIVE_MODEL, workingTreeDirty=False, startedAt="2026-10-12T08:00:00Z")
    data["run"].update(run)
    if usage is not None:
        data["run"].update(usage=usage, usageUnavailableReason=None)
    if failed:
        data["run"]["outcome"] = "FAILED"
        data["findings"] = None
        data["validation"] = {"status": "NO_OUTPUT", "errorCode": "GATEWAY_FAILURE"}
    CandidateRun.model_validate(data)
    return data


def live_ledger(attempts=2, **reserve_overrides):
    from datetime import date

    from contract_eval.candidate_budget import Ledger, reserve
    book = Ledger.model_validate({
        "schema": "mycounsel.spend-ledger.v1", "currency": "EUR", "capMinorUnits": 10000,
        "prices": [{"model": LIVE_MODEL, "provider": "gemini", "region": "eu", "currency": "EUR",
                    "inputMinorUnitsPerMillionTokens": 300, "outputMinorUnitsPerMillionTokens": 1500,
                    "verifiedOn": "2026-10-10", "sourceUrl": "https://example.invalid/prices"}]})
    args = {"entry_id": "res-baseline", "experiment_id": "test-live", "arm": "baseline", "attempts": attempts,
            "model": LIVE_MODEL, "provider": "gemini", "region": "eu", "max_input_tokens": 6000,
            "max_output_tokens": 12096, "retry_multiplier": 2, "today": date(2026, 10, 11)}
    args.update(reserve_overrides)
    reserve(book, **args)
    return book


def test_live_attempts_need_a_reservation_bound_before_dispatch(tmp_path):
    from contract_eval.candidate_experiment import bind_reservation
    out = live_experiment(tmp_path)
    _registered(out, {"attempts/baseline/commercial-base-r1.json": live_run()})
    with pytest.raises(ValueError, match="without a bound budget reservation"):
        aggregate(out)
    experiment = load_experiment(out)
    with pytest.raises(ValueError, match="already has registered attempts"):
        bind_reservation(experiment, live_ledger(), arm_id="baseline", entry_id="res-baseline")


def test_binding_checks_experiment_arm_coverage_and_model(tmp_path):
    from contract_eval.candidate_experiment import bind_reservation
    out = live_experiment(tmp_path)
    experiment = load_experiment(out)
    for book, message in [
        (live_ledger(experiment_id="other-experiment"), "different experiment or arm"),
        (live_ledger(arm="iteration"), "different experiment or arm"),
        (live_ledger(attempts=1), "covers 1 attempts, the arm plans 2"),
    ]:
        with pytest.raises(ValueError, match=message):
            bind_reservation(experiment, book, arm_id="baseline", entry_id="res-baseline")
    with pytest.raises(ValueError, match="no open reservation"):
        bind_reservation(experiment, live_ledger(), arm_id="baseline", entry_id="res-unknown")
    data = experiment.model_dump(by_alias=True)
    data["arms"][0]["model"] = "another-model"
    with pytest.raises(ValueError, match="priced for"):
        bind_reservation(Experiment.model_validate(data), live_ledger(), arm_id="baseline", entry_id="res-baseline")
    ref = bind_reservation(experiment, live_ledger(), arm_id="baseline", entry_id="res-baseline")
    assert (ref.ledgerEntryId, ref.recordedOn, ref.amountMinorUnits) == ("res-baseline", "2026-10-11", 80)
    with pytest.raises(ValueError, match="already has a bound reservation"):
        bind_reservation(experiment, live_ledger(), arm_id="baseline", entry_id="res-baseline")
    replay_only = plan_experiment(CORPUS, experiment_id="test-live", design=design(), arms=[baseline_arm()])
    with pytest.raises(ValueError, match="only a LIVE experiment"):
        bind_reservation(replay_only, live_ledger(), arm_id="baseline", entry_id="res-baseline")


def test_live_arm_reports_usage_and_settles_from_it(tmp_path):
    from datetime import date

    from contract_eval.candidate_budget import remaining_minor_units
    from contract_eval.candidate_experiment import bind_reservation, settle_arm
    out = live_experiment(tmp_path)
    book = live_ledger()
    experiment = load_experiment(out)
    bind_reservation(experiment, book, arm_id="baseline", entry_id="res-baseline")
    save_experiment(experiment, out)
    reported = live_run(usage={"inputTokens": 2000, "outputTokens": 3000, "cacheReadTokens": None,
                               "thinkingTokens": 500, "providerRequestId": "req-1"})
    silent = live_run(failed=True, startedAt="2026-10-12T08:05:00Z")
    _registered(out, {"attempts/baseline/commercial-base-r1.json": reported,
                      "attempts/baseline/commercial-base-r2.json": silent})
    report = aggregate(out)
    summary = report["cells"][0]["summary"]
    assert summary["usage"] == {"attemptsWithUsage": 1, "inputTokens": 2000, "outputTokens": 3000}
    assert (summary["completed"], summary["failed"]) == (1, 1)
    assert report["arms"][0]["budgetReservation"]["ledgerEntryId"] == "res-baseline"
    assert report["cells"][0]["attempts"][0]["usage"]["providerRequestId"] == "req-1"
    markdown = render_markdown(report)
    assert "Budget reservation `res-baseline` of 80 EUR minor units" in markdown
    assert "2000 input and 3000 billed output tokens across 1 attempts" in markdown
    # 2000*300 + 3000*1500 = 5.1 cents rounded up, plus the full 20-cent hold of the silent attempt.
    result = settle_arm(out, book, arm_id="baseline", settlement_id="set-baseline", today=date(2026, 10, 12))
    assert result == {"settlementId": "set-baseline", "amountMinorUnits": 26, "observedAttempts": 2,
                      "attemptsWithoutUsage": 1}
    assert remaining_minor_units(book) == 10000 - 26
    with pytest.raises(ValueError, match="no open reservation"):
        settle_arm(out, book, arm_id="baseline", settlement_id="set-again", today=date(2026, 10, 12))


def test_live_attempt_dated_before_its_reservation_is_refused(tmp_path):
    from contract_eval.candidate_experiment import bind_reservation
    out = live_experiment(tmp_path)
    experiment = load_experiment(out)
    bind_reservation(experiment, live_ledger(), arm_id="baseline", entry_id="res-baseline")
    save_experiment(experiment, out)
    _registered(out, {"attempts/baseline/commercial-base-r1.json": live_run(startedAt="2026-10-10T23:59:00Z")})
    with pytest.raises(ValueError, match="started before its arm's budget reservation"):
        aggregate(out)


def test_usage_shape_is_validated_on_the_recording():
    with pytest.raises(ValidationError, match="never both or neither"):
        live_run(usageUnavailableReason=None)
    with pytest.raises(ValidationError, match="share of billed output"):
        live_run(usage={"inputTokens": 1, "outputTokens": 2, "thinkingTokens": 3})
    data = live_run(usage={"inputTokens": 1, "outputTokens": 2})
    data["run"]["usageUnavailableReason"] = "both"
    with pytest.raises(ValidationError, match="never both or neither"):
        CandidateRun.model_validate(data)


def test_committed_experiment_reports_reproduce():
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "check_candidate_experiments.py")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_cli_round_trip(tmp_path):
    from contract_eval.candidate_experiment import main
    out = tmp_path / "cli"
    run = replay()["run"]
    main(["plan", "--corpus", str(CORPUS), "--out", str(out), "--id", "cli-test", "--mode", "REPLAY",
          "--playbooks", "commercial", "--variants", "base", "--injection-variants", "", "--repetitions", "1",
          "--prompt-version", run["promptVersion"], "--code-revision", run["codeRevision"], "--model", run["model"]])
    main(["add-arm", str(out), "--id", "iteration", "--prompt-version", "p2", "--code-revision", "c" * 40,
          "--model", run["model"], "--change", "x", "--hypothesis", "y"])
    write_attempt(out, "attempts/baseline/commercial-base-r1.json", replay())
    main(["register", str(out)])
    main(["aggregate", str(out), "--out", str(out / "report.json"), "--markdown", str(out / "report.md")])
    report = json.loads((out / "report.json").read_text())
    assert report["schema"] == "mycounsel.candidate-experiment-report.v1"
    assert len(report["arms"]) == 2 and report["comparisons"][0]["comparable"] is False
    assert (out / "report.md").read_text().startswith("# Candidate experiment cli-test")
