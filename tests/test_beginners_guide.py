"""docs/beginners-guide.html walks through the NDA demo with the repository's own data.

The page is one self-contained file, so it carries copies of the contract text, the
stub's citations, its risk calls and the scorecard numbers. These checks fail when a
copy drifts from its source, and when the page starts loading anything from another
host.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from contract_eval.adapters import get_adapter
from contract_eval.api import load_case, score_review

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "beginners-guide.html"
JS_STRING = r'"((?:[^"\\]|\\.)*)"'
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _js_values(key: str) -> list[str]:
    """Every string literal assigned to `key:` in the page's script, decoded."""
    return [json.loads(f'"{raw}"') for raw in re.findall(rf"\b{key}: {JS_STRING}", _guide())]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _nda_scores() -> dict:
    case = load_case("nda")
    review = get_adapter(live=False).review(case.source_text, "nda")
    return score_review(case.source_text, case.expected, review)


def _contract_sections() -> list[tuple[str, str]]:
    """(heading, paragraph) pairs of the NDA, with its line wrapping removed."""
    sections, heading = [], ""
    text = (ROOT / "data" / "nda_sample.md").read_text(encoding="utf-8").strip()
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(block.split())
        if block.startswith("# "):
            continue
        numbered = re.fullmatch(r"## \d+\. (.+)", block)
        if numbered:
            heading = numbered.group(1)
            continue
        sections.append((heading, block))
    return sections


def test_guide_contract_matches_the_nda() -> None:
    assert list(zip(_js_values("title"), _js_values("text"), strict=True)) == _contract_sections()


def test_guide_quotes_are_the_stub_citations() -> None:
    citations = _json("fixtures/nda_stub.json")["citations"]
    expected = [(c["quote"], c["clause_type"]) for c in citations]
    assert list(zip(_js_values("quote"), _js_values("clause"), strict=True)) == expected


def _expected_result(gold: str | None, predicted: str | None) -> str:
    if gold is None:
        return "False alarm"
    if predicted is None:
        return "Missed"
    if gold == predicted:
        return "Correct"
    return "Under-rated" if SEVERITY_RANK[predicted] < SEVERITY_RANK[gold] else "Over-rated"


def test_guide_risk_table_matches_the_gold_set_and_the_stub() -> None:
    gold = _json("expected/nda.json")["risk_flags"]
    predicted = {f["clause_type"]: f["severity"] for f in _json("fixtures/nda_stub.json")["risk_flags"]}
    tbody = re.search(r"<tbody>(.*?)</tbody>", _guide(), re.DOTALL)
    assert tbody, "the risk table is missing"
    rows = {}
    for row in re.findall(r"<tr>(.*?)</tr>", tbody.group(1)):
        name, gold_cell, predicted_cell, result_cell = re.findall(r"<td>(.*?)</td>", row)
        clause = name.split(" <span", 1)[0].lower().replace(" ", "_")
        severity = [re.search(r"<b>(\w+)</b>", c) for c in (gold_cell, predicted_cell)]
        rows[clause] = (
            *(m.group(1).lower() if m else None for m in severity),
            re.sub(r"<[^>]+>", "", result_cell),
        )
    assert set(rows) == set(gold) | set(predicted)
    for clause, shown in rows.items():
        g, p = gold.get(clause), predicted.get(clause)
        assert shown == (g, p, _expected_result(g, p)), clause


SCORE_ROWS = {
    "Clause recall": "clause_recall",
    "Clause precision": "clause_precision",
    "Clause F1": "clause_f1",
    "Risk precision": "risk_precision",
    "Risk recall": "risk_recall",
    "Severity accuracy": "risk_severity_accuracy",
    "Citation grounding": "citation_grounding",
    "Invented quotes": "hallucination_count",
}


def test_guide_scorecard_matches_the_scorer() -> None:
    shown = dict(re.findall(r'<span class="name">([^<]+)</span><span class="val">([^<]+)</span>', _guide()))
    assert set(shown) == set(SCORE_ROWS)
    scores = _nda_scores()
    for label, key in SCORE_ROWS.items():
        value = scores[key]
        expected = str(value) if isinstance(value, int) else f"{value:.2f}"
        assert shown[label] == expected, f"{label}: the page shows {shown[label]}, the scorer gives {expected}"


def test_guide_summary_matches_the_scorer() -> None:
    slip = dict(re.findall(r'<dt>([^<]+)</dt><span class="lead"></span><dd[^>]*>([^<]+)</dd>', _guide()))
    scores = _nda_scores()
    gold_clauses = len(load_case("nda").expected.clause_types)
    confusion = scores["risk_severity_confusion"]
    agreed = sum(n for pair, n in confusion.items() if len(set(pair.split("->"))) == 1)
    assert slip == {
        "Clauses found": f"{round(scores['clause_recall'] * gold_clauses)} / {gold_clauses}",
        "Severity right": f"{agreed} / {sum(confusion.values())}",
        "Quotes found": f"{scores['citation_grounded']} / {scores['citation_total']}",
        "Invented quotes": str(scores["hallucination_count"]),
    }


def test_guide_loads_nothing_from_another_host() -> None:
    page = _guide()
    assert not re.search(r"<(?:script|link|img|iframe|object|embed)\b[^>]*\b(?:src|href)\s*=", page)
    assert "@import" not in page and "url(" not in page
