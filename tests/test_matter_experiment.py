"""The parts of the matter path that guard claims rather than compute scores.

The experiment log must notice when the evaluation split has been tuned on. The live
adapter must show a model only what its condition allows and keep the raw response.
A reviewer session must be bound to one output and say what kind of evidence it is.
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from contract_eval.adapters.matter import LiveMatterAdapter, render_prompt
from contract_eval.matter import MatterReview, load_matter
from contract_eval.matter_cli import evaluate_matter, render_matter
from contract_eval.matter_experiment import default_log_path, eval_guard, read_log
from contract_eval.reviewer_sessions import (
    USEFULNESS_RUBRIC,
    ReviewerSession,
    blank_session,
    summarise_sessions,
    validate_against_review,
)

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "tests" / "fixtures" / "mini_matter"
FIXTURE = TOY / "matters" / "toy" / "fixtures" / "round1.matter.json"


@pytest.fixture
def toy_copy(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(TOY, root)
    return root


# ------------------------------------------------------------------- experiment log


def entry(configuration: str, split: str = "eval", condition: str = "matter") -> dict:
    return {
        "matter_id": "toy", "round_id": "round1", "condition_id": condition,
        "split": split, "configuration_id": configuration,
    }


def guard(entries: list[dict], configuration: str = "B") -> dict:
    return eval_guard(
        entries, matter_id="toy", round_id="round1",
        condition_id="matter", configuration=configuration,
    )


def test_a_first_evaluation_run_is_held_out():
    assert guard([])["contaminated"] is False


def test_rescoring_the_same_configuration_is_not_tuning():
    assert guard([entry("B"), entry("B")])["contaminated"] is False


def test_a_second_configuration_on_the_evaluation_split_is_flagged():
    result = guard([entry("A")])
    assert result["contaminated"] is True
    assert result["other_configurations"] == ["A"]
    assert "not a held-out measurement" in result["note"]


def test_development_runs_never_contaminate():
    assert guard([entry("A", split="dev"), entry("C", split="dev")])["contaminated"] is False


def test_conditions_are_judged_separately():
    """Baseline against matter on the evaluation split is the experiment itself."""
    assert guard([entry("A", condition="baseline")])["contaminated"] is False


def test_a_prompt_change_is_a_configuration_change(toy_copy):
    def current() -> str:
        result = evaluate_matter("toy", "round1", root=toy_copy, conditions=["matter"])
        return result["conditions"][0]["configuration_id"]

    before = current()
    assert current() == before
    prompt = toy_copy / "matters" / "toy" / "prompts" / "matter.md"
    prompt.write_text(prompt.read_text() + "\nBe careful.\n")
    assert current() != before


def test_a_document_shown_is_part_of_the_configuration(toy_copy):
    """The prompt as sent contains the documents, so the two conditions never share an id."""
    result = evaluate_matter("toy", "round1", root=toy_copy)
    ids = {c["configuration_id"] for c in result["conditions"]}
    assert len(ids) == 2


def test_answers_changed_after_an_evaluation_run_are_flagged():
    """Moving a missed issue to the development split must not pass unnoticed."""
    before = {**entry("B"), "gold_sha256": "old"}
    result = eval_guard(
        [before], matter_id="toy", round_id="round1", condition_id="matter",
        configuration="B", gold_sha256="new",
    )
    assert result["contaminated"] is True and result["answers_changed"] is True
    assert "answers for this round changed" in result["note"]

    # Seen under any condition: the baseline run exposed the split just as well.
    other = {**entry("A", condition="baseline"), "gold_sha256": "old"}
    assert eval_guard(
        [other], matter_id="toy", round_id="round1", condition_id="matter",
        configuration="B", gold_sha256="new",
    )["answers_changed"] is True


def test_a_log_line_from_an_older_format_does_not_break_the_guard():
    legacy = {"matter_id": "toy", "round_id": "round1", "condition_id": "matter", "split": "eval"}
    assert guard([legacy])["contaminated"] is False


def test_two_different_output_files_on_the_evaluation_split_are_flagged(toy_copy):
    """Scoring captures is the real path once answers exist, so it is logged by default."""
    fixtures = toy_copy / "matters" / "toy" / "fixtures"
    first = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="eval",
        reviews={"matter": fixtures / "round1.baseline.json"},
    )
    assert first["conditions"][0]["eval_guard"]["contaminated"] is False
    assert len(read_log(default_log_path("toy", toy_copy))) == 1

    again = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="eval",
        reviews={"matter": fixtures / "round1.baseline.json"},
    )
    assert again["conditions"][0]["eval_guard"]["contaminated"] is False

    better = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="eval",
        reviews={"matter": fixtures / "round1.matter.json"},
    )
    assert better["conditions"][0]["eval_guard"]["contaminated"] is True


def test_tuning_after_an_evaluation_run_is_printed_on_the_scorecard(toy_copy):
    log = toy_copy / "experiments" / "toy" / "log.jsonl"
    first = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="eval", log_path=log
    )
    assert first["conditions"][0]["eval_guard"]["contaminated"] is False

    prompt = toy_copy / "matters" / "toy" / "prompts" / "matter.md"
    prompt.write_text(prompt.read_text() + "\nA hint written after seeing the result.\n")
    second = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="eval", log_path=log
    )
    assert second["conditions"][0]["eval_guard"]["contaminated"] is True
    assert "**Not held out.**" in render_matter(second)
    assert len(read_log(log)) == 2


def test_a_development_run_is_logged_without_a_guard(toy_copy):
    log = toy_copy / "log.jsonl"
    result = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="dev", log_path=log
    )
    assert "eval_guard" not in result["conditions"][0]
    assert read_log(log)[0]["split"] == "dev"


def test_a_stub_run_writes_no_log_unless_asked(toy_copy):
    evaluate_matter("toy", "round1", root=toy_copy)
    assert not (toy_copy / "experiments").exists()


# --------------------------------------------------------------------- live adapter


class FakeMessages:
    def __init__(self, raw_text: str, stop_reason: str = "end_turn") -> None:
        self.calls: list[dict] = []
        self._raw_text, self._stop_reason = raw_text, stop_reason

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._raw_text)],
            stop_reason=self._stop_reason,
            model="fake-model-resolved",
            id="req_1",
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )


def fake_client(raw_text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(messages=FakeMessages(raw_text, stop_reason))


def test_a_prompt_contains_only_what_its_condition_may_see():
    loaded = load_matter("toy", TOY)
    baseline = render_prompt(loaded, "round2", "baseline")
    matter = render_prompt(loaded, "round2", "matter")
    assert '<document id="supply" kind="contract"' in baseline
    assert "Reject any surcharge" not in baseline
    assert "five (5) days" not in baseline
    assert "Reject any surcharge" in matter and "five (5) days" in matter


def test_a_prompt_without_the_placeholder_is_refused(toy_copy):
    (toy_copy / "matters" / "toy" / "prompts" / "matter.md").write_text("No slot.\n")
    with pytest.raises(ValueError, match="placeholder"):
        render_prompt(load_matter("toy", toy_copy), "round1", "matter")


def test_the_live_adapter_requests_the_schema_and_keeps_the_raw_response(toy_copy):
    client = fake_client(FIXTURE.read_text())
    adapter = LiveMatterAdapter(model="fake-model", client=client)
    loaded = load_matter("toy", toy_copy)

    review = adapter.review(loaded, "round1", "matter")

    call = client.messages.calls[0]
    assert call["output_format"] is MatterReview
    assert call["model"] == "fake-model"
    assert call["messages"][0]["content"] == render_prompt(loaded, "round1", "matter")
    assert len(review.conflicts) == 2

    captures = list((toy_copy / "captures" / "matters" / "toy").glob("round1.matter.*.json"))
    assert len(captures) == 1
    capture = json.loads(captures[0].read_text())
    assert capture["returned_model"] == "fake-model-resolved"
    # The capture alone is enough to score the run later.
    scored = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"],
        reviews={"matter": captures[0]},
    )
    assert scored["conditions"][0]["scores"]["issue_recall"] == 1.0


def test_a_truncated_response_is_captured_and_never_scored(toy_copy):
    adapter = LiveMatterAdapter(model="m", client=fake_client("{", stop_reason="max_tokens"))
    with pytest.raises(RuntimeError, match="truncated"):
        adapter.review(load_matter("toy", toy_copy), "round1", "matter")
    assert list((toy_copy / "captures" / "matters" / "toy").glob("*.json"))


def test_a_call_that_raises_inside_the_sdk_still_leaves_a_capture(toy_copy):
    """The SDK validates against the schema inside the call, so nothing may come back."""

    class Raising:
        def parse(self, **kwargs):
            raise ValueError("response did not match the schema")

    adapter = LiveMatterAdapter(model="m", client=SimpleNamespace(messages=Raising()))
    with pytest.raises(ValueError, match="did not match"):
        adapter.review(load_matter("toy", toy_copy), "round1", "matter")

    captures = list((toy_copy / "captures" / "matters" / "toy").glob("*.json"))
    assert len(captures) == 1
    record = json.loads(captures[0].read_text())
    assert (record["status"], record["error_type"]) == ("failed", "ValueError")
    assert "raw_text" not in record

    with pytest.raises(ValueError, match="failed attempt"):
        evaluate_matter(
            "toy", "round1", root=toy_copy, conditions=["matter"],
            reviews={"matter": captures[0]},
        )


def test_a_live_run_and_the_later_scoring_of_its_capture_are_one_configuration(toy_copy, monkeypatch):
    client = fake_client(FIXTURE.read_text())
    monkeypatch.setattr(
        "contract_eval.matter_cli.get_matter_adapter",
        lambda live, model=None: LiveMatterAdapter(model="fake-model", client=client),
    )
    live = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="eval", live=True
    )
    capture = next((toy_copy / "captures" / "matters" / "toy").glob("*.json"))
    replayed = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], split="eval",
        reviews={"matter": capture},
    )
    assert live["adapter"] == replayed["adapter"] == "fake-model"
    assert live["conditions"][0]["configuration_id"] == replayed["conditions"][0]["configuration_id"]
    assert replayed["conditions"][0]["eval_guard"]["contaminated"] is False


def test_a_capture_is_only_scored_as_what_it_was_captured_for(toy_copy):
    client = fake_client(FIXTURE.read_text())
    LiveMatterAdapter(model="m", client=client).review(
        load_matter("toy", toy_copy), "round1", "matter"
    )
    capture = next((toy_copy / "captures" / "matters" / "toy").glob("*.json"))
    with pytest.raises(ValueError, match="was captured for"):
        evaluate_matter(
            "toy", "round1", root=toy_copy, conditions=["baseline"],
            reviews={"baseline": capture},
        )


def test_a_review_file_for_a_condition_not_being_scored_is_refused(toy_copy):
    with pytest.raises(ValueError, match="not being scored"):
        evaluate_matter("toy", "round1", root=toy_copy, reviews={"mater": FIXTURE})


def test_conditions_produced_differently_are_not_presented_as_a_comparison(toy_copy):
    result = evaluate_matter("toy", "round1", root=toy_copy, reviews={"matter": FIXTURE})
    assert result["adapter"] == "review-file, stub-fixture"
    report = render_matter(result)
    assert "not produced the same way" in report
    assert "committed fixtures, not model output" not in report


# ----------------------------------------------------------------- reviewer sessions


def review() -> MatterReview:
    return MatterReview.model_validate(json.loads(FIXTURE.read_text()))


def session(**overrides) -> dict:
    blank = blank_session("toy", "round1", review())
    blank.update(
        reviewer_id="R01", evidence_class="practising_lawyer", review_minutes=25,
        minutes_to_reviewable_draft=4,
    )
    for decision in blank["decisions"]:
        decision.update(decision="accepted", usefulness=4)
    blank.update(overrides)
    return blank


def test_a_blank_session_names_the_output_by_hash_and_not_by_condition():
    blank = blank_session("toy", "round1", review())
    assert blank["review_sha256"] == review().canonical_sha256()
    assert "condition" not in json.dumps(blank)
    assert [d["finding_id"] for d in blank["decisions"]] == ["k1", "k2", "p1", "p2", "e1", "e2"]


def test_a_rejection_or_correction_needs_a_written_reason():
    data = session()
    data["decisions"][0].update(decision="rejected", usefulness=1)
    with pytest.raises(ValidationError, match="needs a written reason"):
        ReviewerSession.model_validate(data)
    data["decisions"][0]["reason"] = "The periods apply to different order types."
    ReviewerSession.model_validate(data)


def test_a_reviewer_is_recorded_under_a_pseudonym():
    with pytest.raises(ValidationError, match="pseudonym"):
        ReviewerSession.model_validate(session(reviewer_id="Jane Doe"))


def test_a_session_must_rate_exactly_the_output_it_is_bound_to():
    complete = ReviewerSession.model_validate(session())
    validate_against_review(complete, review())

    partial = session()
    partial["decisions"].pop()
    with pytest.raises(ValueError, match="rate every finding once"):
        validate_against_review(ReviewerSession.model_validate(partial), review())

    other = ReviewerSession.model_validate(session(review_sha256="0" * 64))
    with pytest.raises(ValueError, match="different review output"):
        validate_against_review(other, review())


def test_only_practising_lawyers_other_than_the_author_count_as_pilot_evidence():
    own = ReviewerSession.model_validate(session(evidence_class="author_self_review"))
    summary = summarise_sessions([own])
    assert summary["measured"] is False
    assert summary["sessions_excluded"] == 1

    corrected = session(reviewer_id="R02", review_minutes=35)
    corrected["decisions"][0].update(decision="corrected", usefulness=3, reason="Severity too high.")
    summary = summarise_sessions(
        [own, ReviewerSession.model_validate(session()), ReviewerSession.model_validate(corrected)]
    )
    assert summary["measured"] is True
    assert (summary["sessions"], summary["reviewers"], summary["sessions_excluded"]) == (2, 2, 1)
    assert summary["corrected_rate"] == pytest.approx(1 / 12)
    assert summary["median_review_minutes"] == 30


def test_recorded_sessions_reach_the_scorecard(toy_copy):
    reviews = toy_copy / "matters" / "toy" / "reviews"
    reviews.mkdir()
    (reviews / "R01.json").write_text(json.dumps(session()))
    result = evaluate_matter("toy", "round1", root=toy_copy)
    by_condition = {c["condition_id"]: c for c in result["conditions"]}
    assert by_condition["matter"]["reviewer_usefulness"]["mean_usefulness"] == 4.0
    # The session is bound to the matter output, so it says nothing about the baseline.
    assert by_condition["baseline"]["reviewer_usefulness"]["measured"] is False
    assert "| Reviewer usefulness (1 to 4) | not measured | 4.00 (n=1) |" in render_matter(result)


def test_one_reviewer_cannot_rate_the_same_output_twice(toy_copy):
    reviews = toy_copy / "matters" / "toy" / "reviews"
    reviews.mkdir()
    (reviews / "a.json").write_text(json.dumps(session()))
    (reviews / "b.json").write_text(json.dumps(session()))
    with pytest.raises(ValueError, match="more than one session"):
        evaluate_matter("toy", "round1", root=toy_copy)


def test_the_rubric_has_a_description_for_every_score():
    assert sorted(USEFULNESS_RUBRIC) == [1, 2, 3, 4]
