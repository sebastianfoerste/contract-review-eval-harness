from contract_eval.scorer import _is_grounded

def test_fuzzy_matching_exact():
    source = "The term of this Agreement shall commence on the Effective Date."
    quote = "commence on the Effective Date"
    assert _is_grounded(source, quote)

def test_fuzzy_matching_punctuation_and_caps():
    source = "The term of this Agreement shall commence on the Effective Date."
    # Capitalization differences and missing period
    quote = "Commence On The effective date"
    assert _is_grounded(source, quote)

def test_fuzzy_matching_smart_quotes_and_dashes():
    source = "The parties agree—subject to Section 4—to confidentiality."
    quote = "agree subject to Section 4 to confidentiality"
    assert _is_grounded(source, quote)

def test_fuzzy_matching_token_overlap():
    source = "This Agreement contains the entire agreement of the parties regarding this matter."
    # One word missing/different ("about" instead of "regarding")
    quote = "contains the entire agreement of the parties about this matter"
    # Q_len = 10 words. 9 words overlap. Overlap = 90% (>= 85% threshold)
    assert _is_grounded(source, quote)

def test_fuzzy_matching_hallucination():
    source = "This Agreement contains the entire agreement of the parties regarding this matter."
    # Too many different words
    quote = "completely replaces other random side agreements made by folks"
    assert not _is_grounded(source, quote)
