"""Grounding accepts normalisation differences, not textual alterations.

The prompt requires citations copied verbatim. Case, punctuation, smart quotes and
line wrapping are presentation, so they are normalised away. A substituted or
reordered word changes what the contract says, so it is not a quotation.

These tests previously asserted the opposite: an 85% unordered token-overlap rule
accepted a quote with a word swapped out.
"""

from contract_eval.scorer import _is_grounded, grounded_span


def test_exact_span_is_grounded():
    source = "The term of this Agreement shall commence on the Effective Date."
    assert _is_grounded(source, "commence on the Effective Date")


def test_capitalisation_and_punctuation_are_normalised():
    source = "The term of this Agreement shall commence on the Effective Date."
    assert _is_grounded(source, "Commence On The effective date")


def test_smart_quotes_and_dashes_are_normalised():
    source = "The parties agree—subject to Section 4—to confidentiality."
    assert _is_grounded(source, "agree subject to Section 4 to confidentiality")


def test_line_wrapping_is_normalised():
    source = "The Processor shall notify the Controller within\nfourteen (14) days."
    assert _is_grounded(source, "within fourteen (14) days")


def test_substituted_word_is_not_a_quotation():
    """'about' for 'regarding' alters the text and must not pass as verbatim."""
    source = "This Agreement contains the entire agreement of the parties regarding this matter."
    assert not _is_grounded(source, "contains the entire agreement of the parties about this matter")


def test_reordered_words_are_not_a_quotation():
    source = "This Agreement contains the entire agreement of the parties regarding this matter."
    assert not _is_grounded(source, "the parties regarding this matter contains the entire agreement")


def test_unrelated_text_is_not_grounded():
    source = "This Agreement contains the entire agreement of the parties regarding this matter."
    assert not _is_grounded(source, "completely replaces other random side agreements made by folks")


def test_span_locates_the_match():
    source = "The Receiving Party shall keep all Confidential Information secret."
    span = grounded_span(source, "keep all Confidential Information")
    assert span is not None
    start, end = span
    assert "the receiving party shall keep all confidential information secret"[start:end] == (
        "keep all confidential information"
    )
