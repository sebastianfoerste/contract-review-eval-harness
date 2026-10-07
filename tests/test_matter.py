"""A matter is scored through evidence, per document, per condition, per split.

The numeric assertions run against a toy matter under tests/fixtures. Its answers are
test data and carry no legal judgment, which is why they may be asserted exactly. No
number is asserted for the real matter under matters/: it has no committed output, and
the tests below assert that the harness then scores nothing rather than something.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval.matter import (
    MatterDrift,
    MatterGold,
    MatterIssue,
    MatterReview,
    load_matter,
)
from contract_eval.matter_cli import check_matter, evaluate_matter, list_matters, render_matter
from contract_eval.matter_scorer import (
    ONE_SIDED,
    UNBOUND_AMBIGUOUS,
    UNBOUND_NO_ISSUE,
    UNBOUND_UNRESOLVED,
    conflict_credit,
    resolve_citation,
    score_matter,
)
from contract_eval.scorer import build_normalized_index

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "tests" / "fixtures" / "mini_matter"


def toy_review(name: str) -> MatterReview:
    path = TOY / "matters" / "toy" / "fixtures" / f"{name}.json"
    return MatterReview.model_validate(json.loads(path.read_text()))


@pytest.fixture
def toy():
    return load_matter("toy", TOY)


@pytest.fixture
def toy_copy(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(TOY, root)
    return root


def issue(**overrides) -> dict:
    base = {
        "issue_id": "x.one",
        "task": "position",
        "split": "dev",
        "title": "t",
        "description": "d",
        "materiality": "high",
        "evidence": [{"document_id": "supply", "start": 0, "end": 5, "quote": "# Toy"}],
        "expected_action": "reject",
        "rationale": "r",
        "source_category": "legal_judgment",
    }
    return {**base, **overrides}


# ------------------------------------------------------------------ loading and shape


def test_a_matter_loads_with_every_document_hash_verified(toy):
    assert set(toy.texts) == {"supply", "schedule", "playbook", "update"}
    assert toy.matter.synthetic is True


def test_an_edited_document_is_refused_until_its_hash_is_recorded_again(toy_copy):
    (toy_copy / "docs" / "supply.md").write_text("changed\n")
    with pytest.raises(MatterDrift, match="supply"):
        load_matter("toy", toy_copy)


def test_rounds_accumulate_and_conditions_filter_by_kind(toy):
    assert set(toy.texts_in_round("round1")) == {"supply", "schedule", "playbook"}
    assert set(toy.texts_in_round("round2")) == {"supply", "schedule", "playbook", "update"}
    assert set(toy.visible_texts("round2", "baseline")) == {"supply", "schedule"}
    assert "update" in toy.visible_texts("round2", "matter")


def test_a_matter_cannot_be_declared_non_synthetic(toy_copy):
    manifest = toy_copy / "matters" / "toy" / "matter.json"
    data = json.loads(manifest.read_text())
    data["synthetic"] = False
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        load_matter("toy", toy_copy)


def test_a_conflict_needs_evidence_in_two_documents():
    with pytest.raises(ValidationError, match="at least two documents"):
        MatterIssue.model_validate(issue(task="conflict", expected_action=None))


def test_a_position_needs_an_action_and_an_escalation_must_escalate():
    with pytest.raises(ValidationError, match="needs an expected_action"):
        MatterIssue.model_validate(issue(expected_action=None))
    with pytest.raises(ValidationError, match="expected_action 'escalate'"):
        MatterIssue.model_validate(issue(task="escalation", expected_action="accept"))


def test_a_conclusion_resting_on_law_or_the_playbook_names_its_source():
    for category in ("law", "client_playbook"):
        with pytest.raises(ValidationError, match="requires a source_reference"):
            MatterIssue.model_validate(issue(source_category=category))


def gold(issues: list[dict], status: str = "draft") -> dict:
    return {
        "schema": "contract-review-eval.matter-expected.v1",
        "matter_id": "toy",
        "round_id": "round1",
        "status": {
            "annotator_id": "t", "annotation_status": status,
            "adjudication_status": "not_started",
        },
        "issues": issues,
    }


def test_pending_answers_are_empty_and_written_answers_are_not():
    with pytest.raises(ValidationError, match="must not carry issues"):
        MatterGold.model_validate(gold([issue()], status="pending"))
    with pytest.raises(ValidationError, match="requires at least one issue"):
        MatterGold.model_validate(gold([], status="draft"))
    assert MatterGold.model_validate(gold([], status="pending")).authored is False


def test_two_issues_of_one_task_cannot_share_identical_evidence():
    with pytest.raises(ValidationError, match="identical evidence"):
        MatterGold.model_validate(gold([issue(), issue(issue_id="x.two")]))


def test_answer_offsets_must_resolve_to_the_recorded_quote(toy):
    answers = MatterGold.model_validate(gold([issue()]))
    answers.validate_against_documents(toy.texts_in_round("round1"))

    moved = MatterGold.model_validate(
        gold([issue(evidence=[{"document_id": "supply", "start": 1, "end": 6, "quote": "# Toy"}])])
    )
    with pytest.raises(ValueError, match="does not match the recorded quote"):
        moved.validate_against_documents(toy.texts_in_round("round1"))


def test_an_answer_cannot_cite_a_document_from_a_later_round(toy):
    late = MatterGold.model_validate(
        gold([issue(evidence=[{"document_id": "update", "start": 0, "end": 5, "quote": "# Toy"}])])
    )
    with pytest.raises(ValueError, match="not on the file in round"):
        late.validate_against_documents(toy.texts_in_round("round1"))


def test_a_review_cannot_reference_a_citation_it_does_not_contain():
    with pytest.raises(ValidationError, match="unknown citation ids"):
        MatterReview.model_validate({
            "positions": [{
                "finding_id": "p", "summary": "s", "action": "accept",
                "materiality": "low", "evidence": ["missing"],
            }],
        })


# ------------------------------------------------------------------------- citations


def test_a_quote_is_resolved_in_the_document_it_names(toy):
    indexes = {
        doc: build_normalized_index(text)
        for doc, text in toy.visible_texts("round1", "baseline").items()
    }
    review = toy_review("round1.baseline")
    status = {
        c.citation_id: resolve_citation(c, indexes).status for c in review.citations
    }
    assert status == {
        "c1": "grounded",
        "c2": "grounded",
        "c3": "grounded",
        "c4": "unsupported",
        # Real text, but it is in the schedule and was attributed to the agreement.
        "c5": "misattributed",
    }
    assert resolve_citation(review.citations[4], indexes).found_in == ["schedule"]


def test_a_quote_from_a_document_the_condition_hides_does_not_resolve(toy):
    review = toy_review("round1.matter")
    scores = score_matter(
        toy.visible_texts("round1", "baseline"), toy.gold("round1"), review
    )
    assert scores.citations["not_visible"] == 1
    # The finding that leaned on the hidden playbook loses its binding entirely.
    assert scores.unbound_findings["p1"] == UNBOUND_UNRESOLVED


def test_a_quote_that_occurs_twice_in_its_document_is_ambiguous(toy):
    indexes = {"supply": build_normalized_index(toy.texts["supply"])}
    citation = toy_review("round1.baseline").citations[0].model_copy(
        update={"quote": "TEST FIXTURE"}
    )
    doubled = {"supply": build_normalized_index(toy.texts["supply"] * 2)}
    assert resolve_citation(citation, indexes).status == "grounded"
    assert resolve_citation(citation, doubled).status == "ambiguous"


# --------------------------------------------------------------------------- scoring


def test_the_baseline_fixture_is_scored_as_authored(toy):
    scores = score_matter(
        toy.visible_texts("round1", "baseline"),
        toy.gold("round1"),
        toy_review("round1.baseline"),
    )
    assert scores.issues_total == 5
    assert scores.issue_recall == pytest.approx(2 / 5)
    assert scores.finding_precision == pytest.approx(2 / 3)
    assert scores.material_recall == pytest.approx(2 / 3)
    assert scores.task_recall["escalation"] == 0.0
    assert scores.escalation_precision is None
    assert scores.action_accuracy == 0.0
    assert scores.false_reassurance == ["r1.surcharge_position"]
    assert scores.missed_material == ["r1.price_conflict"]
    assert scores.unbound_findings == {"p2": UNBOUND_UNRESOLVED}
    assert scores.citation_grounding == pytest.approx(3 / 5)


def test_the_matter_fixture_is_scored_as_authored(toy):
    scores = score_matter(
        toy.visible_texts("round1", "matter"),
        toy.gold("round1"),
        toy_review("round1.matter"),
    )
    assert scores.issue_recall == 1.0
    assert scores.finding_precision == pytest.approx(5 / 6)
    assert scores.action_accuracy == 1.0
    assert scores.false_reassurance == []
    # Asking a question the documents already answer is penalised, not rewarded.
    assert scores.escalation_precision == 0.5
    assert scores.unexpected_findings == ["e2"]
    assert scores.citation_grounding == 1.0


def test_a_split_restricts_recall_and_ignores_findings_on_the_other_split(toy):
    scores = score_matter(
        toy.visible_texts("round1", "baseline"),
        toy.gold("round1"),
        toy_review("round1.baseline"),
        split="eval",
    )
    assert scores.issues_total == 3
    assert scores.issue_recall == pytest.approx(1 / 3)
    # k1 found a development issue: left out here, not counted as a false positive.
    assert scores.findings_total == 2
    assert scores.finding_precision == pytest.approx(1 / 2)


def test_a_changed_fact_is_answered_rightly_only_by_a_condition_that_sees_it(toy):
    answers = toy.gold("round2")
    seen = score_matter(
        toy.visible_texts("round2", "matter"), answers, toy_review("round2.matter")
    )
    assert (seen.issue_recall, seen.action_accuracy) == (1.0, 1.0)

    # Without the client update the clause can still be found, and is then accepted,
    # which was right in round one and is wrong now.
    stale = MatterReview.model_validate({
        "positions": [{
            "finding_id": "p1", "summary": "Ten days is acceptable.", "action": "accept",
            "materiality": "medium", "evidence": ["c1"],
        }],
        "citations": [{
            "citation_id": "c1", "document_id": "supply",
            "quote": "deliver the widgets within ten (10) days of each order",
        }],
    })
    blind = score_matter(toy.visible_texts("round2", "baseline"), answers, stale)
    assert (blind.issues_answerable, blind.issue_recall, blind.action_accuracy) == (1, 1.0, 0.0)
    assert blind.false_reassurance == ["r2.delivery_position"]


def test_the_ceiling_follows_the_rules_that_award_credit(toy):
    """A conflict with one side hidden is out of reach; an escalation with its passage shown is not."""
    answers = toy.gold("round1")
    review = toy_review("round1.matter")
    only_supply = {"supply": toy.texts["supply"]}

    strict = score_matter(only_supply, answers, review)
    # Both conflicts need the schedule. The surcharge position sits in the schedule.
    assert strict.issues_answerable == 2

    lenient = score_matter(only_supply, answers, review, credit_rule=lambda c, r: 0.5)
    assert lenient.issues_answerable == 4


def one_sided(toy) -> MatterReview:
    review = toy_review("round1.matter").model_dump(by_alias=True)
    review["conflicts"] = [
        {"finding_id": "k1", "summary": "s", "materiality": "high", "evidence": ["c1"]}
    ]
    return MatterReview.model_validate(review)


def test_the_credit_rule_decides_what_a_one_sided_conflict_earns(toy):
    documents = toy.visible_texts("round1", "matter")
    answers = toy.gold("round1")
    seen: list[tuple[frozenset, frozenset]] = []

    def record(cited, required):
        seen.append((cited, required))
        return 0.5

    half = score_matter(documents, answers, one_sided(toy), credit_rule=record)
    # The rule is also asked for the ceiling, so only the binding call is singled out.
    assert (frozenset({"supply"}), frozenset({"supply", "schedule"})) in seen
    assert half.task_recall["conflict"] == pytest.approx(0.25)

    none = score_matter(documents, answers, one_sided(toy), credit_rule=lambda c, r: 0.0)
    assert none.task_recall["conflict"] == 0.0
    assert none.unbound_findings["k1"] == ONE_SIDED


def test_the_shipped_credit_rule_is_strict():
    """Decided on 2026-10-06: a conflict is shown only by quoting every side of it."""
    both = frozenset({"a", "b"})
    three = frozenset({"a", "b", "c"})
    assert conflict_credit(both, both) == 1.0
    assert conflict_credit(frozenset({"a"}), both) == 0.0
    assert conflict_credit(both, three) == 0.0


def test_quoting_a_whole_document_points_at_nothing(toy):
    """Otherwise one citation per document would earn every issue anchored in it."""
    review = MatterReview.model_validate({
        "positions": [{
            "finding_id": "p1", "summary": "Everything.", "action": "reject",
            "materiality": "high", "evidence": ["c1"],
        }],
        "escalations": [{
            "finding_id": "e1", "question": "Anything?", "reason": "All of it.",
            "evidence": ["c2"],
        }],
        "citations": [
            {"citation_id": "c1", "document_id": "schedule", "quote": toy.texts["schedule"]},
            {"citation_id": "c2", "document_id": "supply", "quote": toy.texts["supply"]},
        ],
    })
    scores = score_matter(toy.visible_texts("round1", "matter"), toy.gold("round1"), review)
    assert scores.citation_grounding == 1.0
    assert scores.issue_recall == 0.0
    assert scores.unexpected_findings == ["e1", "p1"]


def test_a_fragment_of_a_word_is_not_a_quotation(toy):
    indexes = {"supply": build_normalized_index(toy.texts["supply"])}
    fragment = toy_review("round1.baseline").citations[0].model_copy(update={"quote": "nnex"})
    assert resolve_citation(fragment, indexes).status == "unsupported"


def position(finding_id: str, action: str, citation: str = "c3") -> dict:
    return {
        "finding_id": finding_id, "summary": "s", "action": action,
        "materiality": "high", "evidence": [citation],
    }


def with_positions(positions: list[dict], escalations: list[dict] | None = None) -> MatterReview:
    review = toy_review("round1.matter").model_dump(by_alias=True)
    review.update(conflicts=[], positions=positions, escalations=escalations or [])
    return MatterReview.model_validate(review)


@pytest.mark.parametrize("order", [("reject", "accept"), ("accept", "reject")])
def test_contradictory_actions_on_one_issue_are_wrong_in_either_order(toy, order):
    review = with_positions([position("p1", order[0]), position("p2", order[1])])
    scores = score_matter(toy.visible_texts("round1", "matter"), toy.gold("round1"), review)
    assert scores.conflicting_actions == ["r1.surcharge_position"]
    assert scores.action_accuracy == 0.0
    assert scores.false_reassurance == ["r1.surcharge_position"]


def test_an_escalation_filed_as_a_position_is_still_an_escalation(toy):
    """One act, two places to file it. Filing it in the other is not a miss plus a false alarm."""
    review = with_positions([position("p1", "escalate", citation="c6")])
    scores = score_matter(toy.visible_texts("round1", "matter"), toy.gold("round1"), review)
    assert scores.task_recall["escalation"] == 1.0
    assert scores.unexpected_findings == []

    # Any other action on the same passage is a position nobody expected.
    review = with_positions([position("p1", "negotiate", citation="c6")])
    scores = score_matter(toy.visible_texts("round1", "matter"), toy.gold("round1"), review)
    assert scores.task_recall["escalation"] == 0.0
    assert scores.unexpected_findings == ["p1"]


def test_a_point_restated_from_an_earlier_round_is_set_aside(toy):
    """Round two's answers list what is new; a review of the whole file repeats the rest."""
    earlier = toy.gold("round1").issues
    review = toy_review("round1.matter")
    documents = toy.visible_texts("round2", "matter")

    alone = score_matter(documents, toy.gold("round2"), review)
    assert alone.finding_precision == pytest.approx(1 / 6)

    carried = score_matter(documents, toy.gold("round2"), review, earlier_issues=earlier)
    # p2 quotes the delivery clause, which round two also anchors: it stays in and is
    # judged against the new answer. e2 was unexpected in round one and still is.
    assert carried.restated_findings == ["e1", "k1", "k2", "p1"]
    assert carried.findings_total == 2
    assert carried.unexpected_findings == ["e2"]
    assert carried.action_accuracy == 0.0


def test_a_development_scorecard_reveals_nothing_about_evaluation_issues(toy):
    scores = score_matter(
        toy.visible_texts("round1", "matter"), toy.gold("round1"),
        toy_review("round1.matter"), split="dev",
    )
    evaluation = {i.issue_id for i in toy.gold("round1").issues if i.split == "eval"}
    assert not evaluation & {b.issue_id for b in scores.bindings}


def test_quotations_no_finding_relies_on_are_counted(toy):
    scores = score_matter(
        toy.visible_texts("round1", "baseline"), toy.gold("round1"),
        toy_review("round1.baseline"),
    )
    assert scores.unreferenced_citations == 1


def test_an_issue_whose_evidence_sits_inside_another_is_refused():
    wide = issue(issue_id="x.wide", evidence=[
        {"document_id": "supply", "start": 0, "end": 5, "quote": "# Toy"},
        {"document_id": "supply", "start": 6, "end": 12, "quote": "supply"},
    ])
    with pytest.raises(ValidationError, match="contained in the other"):
        MatterGold.model_validate(gold([issue(), wide]))


def test_evidence_shared_by_two_issues_binds_to_neither(toy):
    answers = toy.gold("round1").model_dump(by_alias=True)
    shared = answers["issues"][0]["evidence"][0]
    extra = {
        **answers["issues"][1],
        "issue_id": "r1.second",
        "evidence": [shared, answers["issues"][1]["evidence"][1]],
    }
    answers["issues"].append(extra)
    scores = score_matter(
        toy.visible_texts("round1", "matter"),
        MatterGold.model_validate(answers),
        one_sided(toy),
    )
    assert scores.unbound_findings["k1"] == UNBOUND_AMBIGUOUS


def test_a_grounded_finding_on_nothing_expected_is_reported_as_unexpected(toy):
    scores = score_matter(
        toy.visible_texts("round1", "matter"), toy.gold("round1"), toy_review("round1.matter")
    )
    binding = next(b for b in scores.bindings if b.finding_id == "e2")
    assert binding.reason == UNBOUND_NO_ISSUE


# -------------------------------------------------------------------------- pipeline


def test_the_pipeline_scores_every_condition_side_by_side():
    result = evaluate_matter("toy", "round1", root=TOY)
    by_condition = {c["condition_id"]: c for c in result["conditions"]}
    assert by_condition["baseline"]["scores"]["issue_recall"] == pytest.approx(0.4)
    assert by_condition["matter"]["scores"]["issue_recall"] == 1.0
    assert by_condition["matter"]["reviewer_usefulness"]["measured"] is False

    report = render_matter(result)
    assert "| Issue recall | 0.400 | 1.000 |" in report
    assert "committed fixtures, not model output" in report
    assert "not a validated benchmark" in report


def test_a_condition_without_a_fixture_is_reported_and_not_invented():
    result = evaluate_matter("toy", "round2", root=TOY)
    baseline = next(c for c in result["conditions"] if c["condition_id"] == "baseline")
    assert baseline["scores"] is None
    assert "no stub fixture" in baseline["unavailable"]


def test_a_captured_output_can_be_scored_from_a_file(tmp_path, toy_copy):
    capture = tmp_path / "capture.json"
    raw = (TOY / "matters" / "toy" / "fixtures" / "round1.matter.json").read_text()
    capture.write_text(json.dumps({"raw_text": raw}))
    result = evaluate_matter(
        "toy", "round1", root=toy_copy, conditions=["matter"], reviews={"matter": capture}
    )
    assert result["adapter"] == "review-file"
    assert result["conditions"][0]["scores"]["issue_recall"] == 1.0


def test_the_default_path_never_loads_the_provider_sdk():
    # A fresh interpreter: another test may already have imported the SDK here.
    probe = (
        "import sys; from pathlib import Path; "
        "from contract_eval.matter_cli import evaluate_matter; "
        f"evaluate_matter('toy', 'round1', root=Path({str(TOY)!r})); "
        "sys.exit('anthropic' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", probe], cwd=ROOT).returncode == 0


def test_the_toy_matter_passes_its_structural_check():
    assert check_matter("toy", TOY)["errors"] == []


def test_a_playbook_rule_the_playbook_does_not_contain_is_an_error(toy_copy):
    path = toy_copy / "matters" / "toy" / "expected" / "round1.json"
    data = json.loads(path.read_text())
    data["issues"][2]["playbook_rule"] = "TB-99"
    path.write_text(json.dumps(data))
    assert any("TB-99" in error for error in check_matter("toy", toy_copy)["errors"])


# ---------------------------------------------------------------- the shipped matter


def test_every_shipped_matter_passes_its_structural_check():
    assert "northwind-saas" in list_matters(ROOT)
    for matter_id in list_matters(ROOT):
        assert check_matter(matter_id, ROOT)["errors"] == []


def test_the_shipped_matter_reuses_the_certified_contracts_unchanged():
    loaded = load_matter("northwind-saas", ROOT)
    paths = {d.document_id: d.path for d in loaded.matter.documents}
    for case in ("nda", "saas", "dpa"):
        assert paths[case] == f"data/{case}_sample.md"


def test_every_document_written_for_the_matter_is_marked_synthetic():
    loaded = load_matter("northwind-saas", ROOT)
    for document in loaded.matter.documents:
        assert "SYNTHETIC" in loaded.texts[document.document_id], document.document_id


def test_without_stub_fixtures_the_shipped_matter_scores_nothing():
    """The shipped matter has draft answers and no fixtures, so it scores nothing."""
    for round_ in load_matter("northwind-saas", ROOT).matter.rounds:
        result = evaluate_matter("northwind-saas", round_.round_id, root=ROOT)
        assert result["gold_status"]["annotation_status"] == "draft"
        assert all(c["scores"] is None for c in result["conditions"])
        assert "Not scored: no stub fixture" in render_matter(result)


def test_the_three_conditions_form_a_ladder():
    loaded = load_matter("northwind-saas", ROOT)
    shown = [
        set(loaded.visible_texts("round2", c)) for c in ("baseline", "sources", "matter")
    ]
    assert shown[0] < shown[1] < shown[2]
    assert shown[0] == {"nda", "saas", "dpa", "vendor_response"}
    assert {"client_instructions", "playbook", "client_update"} <= shown[2] - shown[1]


# ------------------------------------------------------------------------------- cli


def test_the_commands_are_reachable_from_the_entry_point():
    check = subprocess.run(
        [sys.executable, "-m", "contract_eval", "matter-check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "matter check passed" in check.stdout

    scored = subprocess.run(
        [sys.executable, "-m", "contract_eval", "matter-evaluate",
         "--root", str(TOY), "--matter", "toy", "--split", "eval"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert scored.returncode == 0, scored.stdout + scored.stderr
    assert "Split: eval." in scored.stdout


def run_sync(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/matter_sync.py", "--root", str(root), *flags],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_the_sync_script_writes_nothing_when_an_answer_no_longer_resolves(toy_copy):
    """A new document hash recorded beside a stale answer would load cleanly and be wrong."""
    manifest = toy_copy / "matters" / "toy" / "matter.json"
    before = manifest.read_text()
    supply = toy_copy / "docs" / "supply.md"
    supply.write_text(supply.read_text().replace("Annex R", "Annex Q"))

    result = run_sync(toy_copy, "--write")
    assert result.returncode == 1
    assert "r1.returns_annex" in result.stdout
    assert manifest.read_text() == before
    with pytest.raises(MatterDrift):
        load_matter("toy", toy_copy)


def test_a_passage_that_repeats_once_case_is_ignored_is_refused(toy_copy):
    supply = toy_copy / "docs" / "supply.md"
    supply.write_text(supply.read_text() + "\nRETURNS ARE HANDLED AS SET OUT IN ANNEX R\n")
    result = run_sync(toy_copy, "--write")
    assert result.returncode == 1
    assert "once case and punctuation are ignored" in result.stdout


def test_with_answers_pending_a_round_scores_nothing_even_when_output_exists(toy_copy):
    """The harness claims hand-authored answers, so it must not produce a number first."""
    path = toy_copy / "matters" / "toy" / "expected" / "round1.json"
    data = json.loads(path.read_text())
    data["issues"] = []
    data["status"]["annotation_status"] = "pending"
    path.write_text(json.dumps(data))

    result = evaluate_matter("toy", "round1", root=toy_copy)
    assert all(c["scores"] is None for c in result["conditions"])
    assert all("review_sha256" in c for c in result["conditions"])
    report = render_matter(result)
    assert "Nothing is scored" in report and "Answers: pending." in report
    assert not (toy_copy / "experiments").exists()


def test_the_sync_script_reports_clean_for_committed_matters():
    for root in (ROOT, TOY):
        result = subprocess.run(
            [sys.executable, "scripts/matter_sync.py", "--root", str(root)],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "matter sync clean" in result.stdout
