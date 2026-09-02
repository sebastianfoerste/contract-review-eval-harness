"""Pure scoring functions. Each measures one dimension of contract-review quality."""

from dataclasses import dataclass, field

from contract_eval.models import Citation


@dataclass
class ClauseScore:
    precision: float
    recall: float
    f1: float


@dataclass
class CitationScore:
    grounded: int
    total: int
    grounding_rate: float
    spans: list[tuple[int, int] | None] = field(default_factory=list)


@dataclass
class SpanCoverage:
    """Clause coverage measured by where a review cited, not by what it called things."""

    covered: list[str]
    uncovered: list[str]
    coverage: float
    unlocated_citations: int


@dataclass
class RiskScore:
    precision: float
    recall: float
    f1: float
    identified: int
    expected_total: int
    predicted_total: int
    false_positives: list[str]
    missed: list[str]
    severity_accuracy: float
    severity_confusion: dict[str, int]


def clause_scores(expected: list[str], predicted: list[str]) -> ClauseScore:
    exp, pred = set(expected), set(predicted)
    tp = len(exp & pred)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(exp) if exp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return ClauseScore(precision, recall, f1)


def risk_flag_accuracy(expected: dict[str, str], predicted: dict[str, str]) -> float:
    """Share of expected flags predicted at the expected severity.

    Blind to false positives by construction: a review that adds twenty spurious
    high-risk findings scores the same as one that adds none. Report it alongside
    `risk_metrics`, never on its own.
    """
    if not expected:
        return 0.0
    matched = sum(1 for clause_type, severity in expected.items() if predicted.get(clause_type) == severity)
    return matched / len(expected)


def risk_metrics(expected: dict[str, str], predicted: dict[str, str]) -> RiskScore:
    """Score risk identification and severity separately.

    Identification is precision/recall/F1 over which clauses were flagged at all,
    so an over-flagging review loses precision. Severity accuracy is then measured
    only on the clauses both sides flagged, which keeps a severity mistake
    distinguishable from a missed risk.
    """
    exp_keys, pred_keys = set(expected), set(predicted)
    tp_keys = exp_keys & pred_keys

    # Empty-set semantics, stated so they cannot drift:
    #   nothing expected, nothing predicted -> a correct review of a clean contract, 1.0
    #   nothing expected, something predicted -> every prediction is a false positive,
    #     so precision 0.0; there was nothing to miss, so recall is vacuously 1.0
    #   something expected, nothing predicted -> no false positives, so precision is
    #     vacuously 1.0; everything was missed, so recall 0.0
    precision = len(tp_keys) / len(pred_keys) if pred_keys else 1.0
    recall = len(tp_keys) / len(exp_keys) if exp_keys else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    severity_correct = sum(1 for k in tp_keys if predicted[k] == expected[k])
    severity_accuracy = severity_correct / len(tp_keys) if tp_keys else 0.0

    confusion: dict[str, int] = {}
    for k in sorted(tp_keys):
        confusion[f"{expected[k]}->{predicted[k]}"] = (
            confusion.get(f"{expected[k]}->{predicted[k]}", 0) + 1
        )

    return RiskScore(
        precision=precision,
        recall=recall,
        f1=f1,
        identified=len(tp_keys),
        expected_total=len(exp_keys),
        predicted_total=len(pred_keys),
        false_positives=sorted(pred_keys - exp_keys),
        missed=sorted(exp_keys - pred_keys),
        severity_accuracy=severity_accuracy,
        severity_confusion=confusion,
    )


import string

_PUNCTUATION = frozenset(string.punctuation + "“”‘’–—")


def normalize_text(text: str) -> str:
    t = text.lower()
    for p in string.punctuation + "“”‘’–—":
        t = t.replace(p, " ")
    return " ".join(t.split())


def grounded_span(source_text: str, quote: str) -> tuple[int, int] | None:
    """Return the (start, end) span of `quote` in the normalized source, or None.

    Matching is an exact substring comparison after normalising case, punctuation
    and whitespace. The prompt demands verbatim quotation, so anything short of a
    contiguous match is not a quotation.

    This replaces an unordered token-overlap test at 85 percent, which compared
    `set(quote_words)` against `set(window_words)` and therefore ignored word order
    entirely: a reordered or partially substituted quote could be accepted as
    grounded, which is exactly the failure the hallucination count exists to catch.
    """
    norm_source = normalize_text(source_text)
    norm_quote = normalize_text(quote)
    if not norm_quote:
        return None
    start = norm_source.find(norm_quote)
    if start == -1:
        return None
    return (start, start + len(norm_quote))


def _is_grounded(source_text: str, quote: str) -> bool:
    return grounded_span(source_text, quote) is not None


def citation_grounding(source_text: str, citations: list[Citation]) -> CitationScore:
    spans = [grounded_span(source_text, c.quote) for c in citations]
    total = len(citations)
    grounded = sum(1 for span in spans if span is not None)
    rate = grounded / total if total else 0.0
    return CitationScore(grounded, total, rate, spans)


def count_hallucinations(source_text: str, citations: list[Citation]) -> int:
    return sum(1 for c in citations if not _is_grounded(source_text, c.quote))



def span_coverage(
    source_text: str,
    clause_anchors: dict[str, str],
    citations: list[Citation],
) -> SpanCoverage:
    """Did the review quote from inside each gold clause?

    Label-based clause scoring asks whether a review used the gold set's name for a
    clause. This asks whether it engaged with the clause at all, by checking that at
    least one grounded citation lands inside that clause's region of the document. A
    review calling a clause `audits_and_inspections` instead of `audit_rights` scores
    identically here, because vocabulary never enters the comparison.

    Each clause's region runs from its own anchor to the start of the next anchor in
    document order, so a citation cannot be credited to a neighbouring clause. An
    earlier fixed-width window let a single quote satisfy three adjacent clauses.

    It measures citation placement, not comprehension: quoting inside a clause is
    evidence of engagement, not of a correct conclusion about it.
    """
    norm_source = normalize_text(source_text)
    cited_spans = [s for s in (grounded_span(source_text, c.quote) for c in citations) if s]
    unlocated = len(citations) - len(cited_spans)

    located: list[tuple[int, str]] = []
    unlocatable: list[str] = []
    for clause_type, anchor in clause_anchors.items():
        start = norm_source.find(normalize_text(anchor))
        if start == -1:
            unlocatable.append(clause_type)
        else:
            located.append((start, clause_type))
    located.sort()

    boundaries = [start for start, _ in located] + [len(norm_source)]
    covered, uncovered = [], list(unlocatable)
    for index, (start, clause_type) in enumerate(located):
        region_end = boundaries[index + 1]
        hit = any(c_start < region_end and c_end > start for c_start, c_end in cited_spans)
        (covered if hit else uncovered).append(clause_type)

    total = len(clause_anchors)
    return SpanCoverage(
        covered=sorted(covered),
        uncovered=sorted(uncovered),
        coverage=len(covered) / total if total else 0.0,
        unlocated_citations=unlocated,
    )


@dataclass
class NormalizedIndex:
    """Normalized text plus the raw character index each normalized character came from.

    Matching has to happen on normalized text, because a quotation legitimately differs
    from the source in case, punctuation and line wrapping. Reporting has to happen in
    raw offsets, because that is where a gold obligation actually lives. Without the
    map between them, a normalized match cannot be located in the document, which is
    why the previous anchors could only be found by a second normalized search.

    `raw_positions[i]` is the raw index of normalized character `i`. Indices are Python
    characters, so a source containing an umlaut or a typographic dash maps correctly.
    """

    normalized: str
    raw_positions: list[int]

    def to_raw_span(self, start: int, end: int) -> tuple[int, int]:
        if start < 0 or end > len(self.normalized) or start >= end:
            raise ValueError(f"normalized span [{start},{end}) is outside the text")
        raw_start = self.raw_positions[start]
        raw_end = self.raw_positions[end - 1] + 1
        return raw_start, raw_end

    def find_all(self, needle: str) -> list[tuple[int, int]]:
        """Every raw span whose normalized text equals `needle`."""
        if not needle:
            return []
        spans: list[tuple[int, int]] = []
        cursor = self.normalized.find(needle)
        while cursor != -1:
            spans.append(self.to_raw_span(cursor, cursor + len(needle)))
            cursor = self.normalized.find(needle, cursor + 1)
        return spans


def build_normalized_index(source_text: str) -> NormalizedIndex:
    """Normalize once, retaining the raw position of every surviving character."""
    chars: list[str] = []
    positions: list[int] = []
    pending_space = False

    for raw_index, char in enumerate(source_text):
        lowered = char.lower()
        if lowered in _PUNCTUATION or lowered.isspace():
            # Collapse any run of punctuation and whitespace to a single separator.
            pending_space = bool(chars)
            continue
        if pending_space:
            chars.append(" ")
            positions.append(raw_index)
            pending_space = False
        chars.append(lowered)
        positions.append(raw_index)

    return NormalizedIndex("".join(chars), positions)
