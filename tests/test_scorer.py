from contract_eval.models import Citation
from contract_eval.scorer import (
    citation_grounding,
    clause_scores,
    count_hallucinations,
    risk_flag_accuracy,
)


def test_clause_scores_f1():
    s = clause_scores(expected=["a", "b", "c", "d"], predicted=["a", "b", "x"])
    assert round(s.precision, 3) == 0.667  # 2 of 3 predicted correct
    assert s.recall == 0.5  # 2 of 4 expected found
    assert round(s.f1, 3) == 0.571


def test_risk_flag_accuracy_partial():
    acc = risk_flag_accuracy(
        expected={"term": "high", "definition": "medium"},
        predicted={"term": "high", "definition": "low"},
    )
    assert acc == 0.5  # 1 of 2 severities matched


def test_citation_grounding_and_hallucinations():
    source = "The Receiving Party shall keep all Confidential Information secret."
    citations = [
        Citation(quote="keep all Confidential Information secret", clause_type="confidentiality"),
        Citation(quote="auto-renews every 99 years", clause_type="term"),  # fabricated
    ]
    cs = citation_grounding(source, citations)
    assert cs.grounded == 1
    assert cs.total == 2
    assert cs.grounding_rate == 0.5
    assert count_hallucinations(source, citations) == 1


def test_risk_metrics_penalise_false_positives():
    """risk_flag_accuracy alone cannot see over-flagging; risk precision must."""
    from contract_eval.scorer import risk_flag_accuracy, risk_metrics

    expected = {"term": "high"}
    predicted = {"term": "high", **{f"spurious_{i}": "high" for i in range(20)}}

    assert risk_flag_accuracy(expected, predicted) == 1.0

    risk = risk_metrics(expected, predicted)
    assert risk.recall == 1.0
    assert risk.precision < 0.05
    assert len(risk.false_positives) == 20
    assert risk.severity_accuracy == 1.0


def test_risk_metrics_separate_missed_risk_from_wrong_severity():
    from contract_eval.scorer import risk_metrics

    expected = {"a": "high", "b": "high"}
    risk = risk_metrics(expected, {"a": "low"})

    assert risk.missed == ["b"]
    assert risk.identified == 1
    assert risk.severity_accuracy == 0.0
    assert risk.severity_confusion == {"high->low": 1}


def test_grounding_requires_a_contiguous_span_not_token_overlap():
    """A reordered quote is not a quotation.

    The previous implementation compared unordered token sets at 85% overlap, so
    shuffled words scored as grounded.
    """
    from contract_eval.models import Citation
    from contract_eval.scorer import citation_grounding, grounded_span

    source = "The Receiving Party shall keep all Confidential Information secret."

    assert grounded_span(source, "shall keep all Confidential Information secret") is not None
    assert grounded_span(source, "Confidential secret Information keep all shall") is None
    assert grounded_span(source, "shall keep all Confidential Information public") is None

    score = citation_grounding(source, [Citation(quote="keep all Confidential", clause_type="c")])
    assert score.grounded == 1
    assert score.spans[0] is not None


def _nda():
    import json
    from pathlib import Path

    from contract_eval.models import ExpectedAnswer

    root = Path(__file__).resolve().parents[1]
    src = (root / "data" / "nda_sample.md").read_text(encoding="utf-8")
    exp = ExpectedAnswer.model_validate(
        json.loads((root / "expected" / "nda.json").read_text(encoding="utf-8"))
    )
    return src, exp


def test_span_coverage_is_independent_of_clause_labels():
    """The whole point: renaming a clause must not change coverage."""
    from contract_eval.models import Citation
    from contract_eval.scorer import span_coverage

    src, exp = _nda()
    quote = "shall remain in effect in perpetuity"

    gold_name = span_coverage(src, exp.clause_anchors, [Citation(quote=quote, clause_type="term")])
    odd_name = span_coverage(
        src, exp.clause_anchors, [Citation(quote=quote, clause_type="duration_of_obligations")]
    )
    assert gold_name.coverage == odd_name.coverage
    assert gold_name.covered == odd_name.covered == ["term"]


def test_span_coverage_discriminates():
    """It must be able to fail, and a single quote must not satisfy its neighbours."""
    from contract_eval.models import Citation
    from contract_eval.scorer import span_coverage

    src, exp = _nda()
    total = len(exp.clause_anchors)

    assert span_coverage(src, exp.clause_anchors, []).coverage == 0.0

    one = span_coverage(
        src,
        exp.clause_anchors,
        [Citation(quote="shall remain in effect in perpetuity", clause_type="term")],
    )
    assert one.coverage == 1 / total
    assert one.covered == ["term"]

    everything = span_coverage(
        src,
        exp.clause_anchors,
        [Citation(quote=a, clause_type=c) for c, a in exp.clause_anchors.items()],
    )
    assert everything.coverage == 1.0
    assert everything.uncovered == []


def test_ungrounded_citations_do_not_earn_coverage():
    from contract_eval.models import Citation
    from contract_eval.scorer import span_coverage

    src, exp = _nda()
    result = span_coverage(
        src,
        exp.clause_anchors,
        [Citation(quote="a clause that does not appear anywhere", clause_type="term")],
    )
    assert result.coverage == 0.0
    assert result.unlocated_citations == 1


def test_duplicate_canonical_risk_flags_are_visible_not_silently_merged():
    """Two labels collapsing onto one clause used to keep whichever came last."""
    from contract_eval.cli import canonicalise_risk_flags
    from contract_eval.models import RiskFlag

    aliases = {"sub_processors": "subprocessors"}

    conflicting = [
        RiskFlag(clause_type="sub_processors", severity="high", rationale="a"),
        RiskFlag(clause_type="subprocessors", severity="low", rationale="b"),
    ]
    flags, duplicates, conflicts = canonicalise_risk_flags(conflicting, aliases)
    assert duplicates == ["subprocessors"]
    assert conflicts == ["subprocessors"], "contradictory severities must be a conflict"
    assert flags["subprocessors"] == "high", "first prediction wins, deterministically"

    agreeing = [
        RiskFlag(clause_type="sub_processors", severity="high", rationale="a"),
        RiskFlag(clause_type="subprocessors", severity="high", rationale="b"),
    ]
    _, duplicates, conflicts = canonicalise_risk_flags(agreeing, aliases)
    assert duplicates == ["subprocessors"]
    assert conflicts == [], "a repeated flag agreeing with itself is not a conflict"


def test_risk_metric_empty_set_semantics_are_defined():
    """Documented so they cannot drift silently."""
    from contract_eval.scorer import risk_metrics

    both_empty = risk_metrics({}, {})
    assert (both_empty.precision, both_empty.recall, both_empty.f1) == (1.0, 1.0, 1.0)

    nothing_expected = risk_metrics({}, {"a": "high"})
    assert (nothing_expected.precision, nothing_expected.recall) == (0.0, 1.0)
    assert nothing_expected.f1 == 0.0

    nothing_predicted = risk_metrics({"a": "high"}, {})
    assert (nothing_predicted.precision, nothing_predicted.recall) == (1.0, 0.0)
    assert nothing_predicted.f1 == 0.0


def test_short_quotes_counts_grounded_quotes_under_the_floor():
    """A one- or two-word match is grounded almost anywhere and identifies nothing."""
    from contract_eval.models import Citation
    from contract_eval.scorer import MIN_QUOTE_WORDS, count_hallucinations, short_quotes

    source = "The Receiving Party shall keep all Confidential Information secret."
    citations = [
        Citation(quote="the", clause_type="a"),  # grounded, one word
        Citation(quote="keep all", clause_type="b"),  # grounded, two words
        Citation(quote="keep all Confidential", clause_type="c"),  # grounded, at the floor
        Citation(quote="auto-renews every 99 years", clause_type="d"),  # not grounded
    ]

    assert MIN_QUOTE_WORDS == 3
    assert short_quotes(source, citations) == 2
    # An ungrounded citation is a hallucination, never a short quote as well.
    assert count_hallucinations(source, citations) == 1
    assert short_quotes(source, citations, minimum_words=4) == 3
    assert short_quotes(source, []) == 0


def test_short_quotes_counts_a_fragment_of_a_word_as_one_word():
    """Grounding is a substring search, so `confiden` matches inside `confidential`."""
    from contract_eval.models import Citation
    from contract_eval.scorer import grounded_span, short_quotes

    source = "The Receiving Party shall keep all Confidential Information secret."
    fragment = [Citation(quote="confiden", clause_type="a")]

    assert grounded_span(source, "confiden") is not None
    assert short_quotes(source, fragment) == 1


def test_risk_flags_without_evidence_needs_a_grounded_quote_inside_the_flagged_clause():
    from contract_eval.models import Citation
    from contract_eval.scorer import risk_flags_without_evidence

    src, exp = _nda()
    anchors = exp.clause_anchors
    flagged = ["term", "governing_law"]
    inside_term = [Citation(quote=anchors["term"], clause_type="anything")]

    assert risk_flags_without_evidence(src, anchors, flagged, inside_term) == ["governing_law"]
    assert risk_flags_without_evidence(src, anchors, flagged, []) == ["governing_law", "term"]
    # An ungrounded quote is no evidence.
    fabricated = [Citation(quote="a clause that does not appear anywhere", clause_type="term")]
    assert risk_flags_without_evidence(src, anchors, flagged, fabricated) == ["governing_law", "term"]
    # Nothing flagged, nothing to report.
    assert risk_flags_without_evidence(src, anchors, [], []) == []


def test_risk_flags_without_evidence_ignores_a_flag_with_no_anchor():
    """A false positive has no anchor to check; risk precision already penalises it."""
    from contract_eval.scorer import risk_flags_without_evidence

    src, exp = _nda()
    assert risk_flags_without_evidence(src, exp.clause_anchors, ["spurious"], []) == []
    unlocatable = {**exp.clause_anchors, "ghost": "an anchor that is not in the contract"}
    assert risk_flags_without_evidence(src, unlocatable, ["ghost"], []) == []


def test_risk_flags_without_evidence_uses_the_span_coverage_regions():
    """Both read the same regions, so flagging every clause reports exactly the uncovered ones."""
    from contract_eval.models import Citation
    from contract_eval.scorer import risk_flags_without_evidence, span_coverage

    src, exp = _nda()
    anchors = exp.clause_anchors
    citations = [
        Citation(quote=anchors["term"], clause_type="term"),
        Citation(quote="shall remain in effect in perpetuity", clause_type="term"),
    ]

    coverage = span_coverage(src, anchors, citations)
    assert risk_flags_without_evidence(src, anchors, list(anchors), citations) == coverage.uncovered
    assert coverage.covered == ["term"]


def test_span_coverage_regions_run_from_each_anchor_to_the_next():
    """Pinned on a hand-checkable document, so the shared region helper cannot drift."""
    from contract_eval.models import Citation
    from contract_eval.scorer import span_coverage

    source = "Preamble words. Alpha clause text here. Beta clause text here. Gamma clause text here."
    anchors = {"gamma": "Gamma clause", "alpha": "Alpha clause", "beta": "Beta clause"}

    preamble = span_coverage(source, anchors, [Citation(quote="Preamble words", clause_type="x")])
    assert preamble.covered == [] and preamble.coverage == 0.0

    # "text here" first occurs inside alpha's region, which ends where beta's anchor starts.
    alpha = span_coverage(source, anchors, [Citation(quote="text here", clause_type="x")])
    assert alpha.covered == ["alpha"] and alpha.uncovered == ["beta", "gamma"]
    assert alpha.coverage == 1 / 3

    # A quote straddling the alpha/beta boundary is credited to both, and to nothing else.
    straddle = span_coverage(source, anchors, [Citation(quote="here. Beta", clause_type="x")])
    assert straddle.covered == ["alpha", "beta"]

    # The last region runs to the end of the document.
    last = span_coverage(source, anchors, [Citation(quote="Gamma clause text here", clause_type="x")])
    assert last.covered == ["gamma"]
