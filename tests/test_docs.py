"""Offline checks on the documentation.

Relative links must resolve to files that exist, docs/metrics.md must define every
scorecard row, and every GitHub issue form must be well formed. Nothing here touches
the network.

PyYAML is not a dependency of the harness. When it is installed, the issue forms are
parsed with it; otherwise a minimal structural check runs instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from contract_eval.adapters import get_adapter
from contract_eval.api import load_case, score_review
from contract_eval.cli import render_multi
from contract_eval.scorecard import render
from contract_eval.scorer import CitationScore, ClauseScore

ROOT = Path(__file__).resolve().parent.parent
LINKED_DOCS = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    *sorted((ROOT / "docs").glob("*.md")),
]
ISSUE_FORMS = sorted(
    p for p in (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml") if p.name != "config.yml"
)

INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def _link_targets(markdown: str) -> list[str]:
    text = INLINE_CODE.sub("", FENCE.sub("", markdown))
    return INLINE_LINK.findall(text) + REFERENCE_LINK.findall(text)


def _is_external(target: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE)) or target.startswith("//")


@pytest.mark.parametrize("doc", LINKED_DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    assert doc.is_file(), f"{doc.relative_to(ROOT)} is missing"
    broken = []
    for target in _link_targets(doc.read_text(encoding="utf-8")):
        target = target.strip("<>")
        if _is_external(target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0].split("?", 1)[0]
        if not path:
            continue
        resolved = (ROOT / path.lstrip("/")) if path.startswith("/") else (doc.parent / path)
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"{doc.relative_to(ROOT)} links to missing files: {broken}"


def _row_labels(markdown: str) -> set[str]:
    labels = set()
    for line in markdown.splitlines():
        if not line.startswith("| "):
            continue
        label = line.split("|")[1].strip()
        if label and label != "Dimension" and not set(label) <= set("-: "):
            labels.add(label)
    return labels


def _scorecard_labels() -> set[str]:
    """Every row label the single-case and multi-case scorecards actually render."""
    case = load_case("nda")
    review = get_adapter(live=False).review(case.source_text, "nda")
    s = score_review(case.source_text, case.expected, review)
    single = render(
        "nda",
        ClauseScore(s["clause_precision"], s["clause_recall"], s["clause_f1"]),
        s["risk_flag_accuracy"],
        CitationScore(s["citation_grounded"], s["citation_total"], s["citation_grounding"]),
        s["hallucination_count"],
        s,
    )
    return _row_labels(single) | _row_labels(render_multi({"nda": s}))


def test_metrics_doc_has_a_section_for_every_scorecard_row() -> None:
    labels = _scorecard_labels()
    assert len(labels) >= 14, sorted(labels)
    headings = {
        line[3:].strip()
        for line in (ROOT / "docs" / "metrics.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    }
    missing = sorted(labels - headings)
    assert not missing, f"docs/metrics.md has no '## ' section for: {missing}"


FORM_ELEMENT_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def _check_form_structure(text: str, name: str) -> None:
    """Minimal check used when PyYAML is not installed."""
    assert "\t" not in text, f"{name}: tabs are not valid YAML indentation"
    top_level = {m.group(1) for m in re.finditer(r"^([a-z_]+):", text, re.MULTILINE)}
    for key in ("name", "description", "labels", "body"):
        assert key in top_level, f"{name}: missing top-level '{key}'"
    types = re.findall(r"^  - type:\s*(\S+)\s*$", text, re.MULTILINE)
    assert types, f"{name}: body has no elements"
    assert set(types) <= FORM_ELEMENT_TYPES, f"{name}: unknown element types {set(types) - FORM_ELEMENT_TYPES}"
    ids = re.findall(r"^    id:\s*(\S+)\s*$", text, re.MULTILINE)
    assert len(ids) == len(set(ids)), f"{name}: duplicate ids {ids}"
    assert len(ids) == sum(t != "markdown" for t in types), f"{name}: every input element needs an id"


def _check_form_parsed(form: dict, name: str) -> None:
    assert isinstance(form, dict), f"{name}: not a mapping"
    for key in ("name", "description", "labels", "body"):
        assert form.get(key), f"{name}: missing or empty '{key}'"
    assert isinstance(form["labels"], list), f"{name}: labels must be a list"
    ids = []
    for element in form["body"]:
        assert element["type"] in FORM_ELEMENT_TYPES, f"{name}: unknown type {element['type']}"
        if element["type"] == "markdown":
            assert element["attributes"]["value"], f"{name}: empty markdown element"
            continue
        ids.append(element["id"])
        assert element["attributes"]["label"], f"{name}: element {element['id']} has no label"
    assert ids and len(ids) == len(set(ids)), f"{name}: ids must exist and be unique: {ids}"


def test_issue_forms_exist() -> None:
    names = {p.name for p in ISSUE_FORMS}
    assert {"bug.yml", "new-case.yml", "adapter.yml", "annotator.yml"} <= names, names
    assert (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").is_file()


@pytest.mark.parametrize("form_path", ISSUE_FORMS, ids=lambda p: p.name)
def test_issue_form_is_well_formed(form_path: Path) -> None:
    text = form_path.read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:
        _check_form_structure(text, form_path.name)
        return
    _check_form_parsed(yaml.safe_load(text), form_path.name)


def test_issue_template_config_is_well_formed() -> None:
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:
        assert re.search(r"^blank_issues_enabled:\s*(true|false)\s*$", text, re.MULTILINE)
        return
    config = yaml.safe_load(text)
    assert isinstance(config.get("blank_issues_enabled"), bool)
    for link in config.get("contact_links", []):
        assert link["name"] and link["url"].startswith("https://") and link["about"]


def test_annotator_form_warns_against_real_client_data() -> None:
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "annotator.yml").read_text(encoding="utf-8")
    assert "real client data" in text


def test_the_multi_case_scorecard_renders_the_same_rows_as_the_single_case_one() -> None:
    """`evaluate --case all` must not silently drop a row the single-case table shows."""
    case = load_case("nda")
    review = get_adapter(live=False).review(case.source_text, "nda")
    s = score_review(case.source_text, case.expected, review)
    single = render(
        "nda",
        ClauseScore(s["clause_precision"], s["clause_recall"], s["clause_f1"]),
        s["risk_flag_accuracy"],
        CitationScore(s["citation_grounded"], s["citation_total"], s["citation_grounding"]),
        s["hallucination_count"],
        s,
    )
    multi = render_multi({"nda": s})
    assert _row_labels(multi) == _row_labels(single)
    assert {"Short citations", "Risk flags without evidence"} <= _row_labels(multi)
