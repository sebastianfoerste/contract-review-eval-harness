"""Every statutory citation the harness authors has a row in docs/legal-currency.md.

The gold sets are human legal judgement, and their rationales cite provisions. Nothing
used to record when, or against what, a citation was last checked. The ledger does;
this test keeps it complete: a citation added to a gold set, a draft, a fixture, the
robustness campaign, a contract or a guide without a ledger row fails here.

Model output under examples/ is not a repository claim and is not scanned. Nothing
here touches the network: the ledger's URLs are checked by a reader, not by code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "legal-currency.md"

# Harness-authored text that may state a legal proposition.
SCANNED_GLOBS = (
    "expected/*.json",
    "candidates/expected/*.json",
    "annotations/drafts/*.json",
    "annotations/pack/**/*.md",
    "annotations/pack/**/*.json",
    "annotations/README.md",
    "candidates/README.md",
    "fixtures/*_stub.json",
    "robustness/*.json",
    "data/*.md",
    "candidates/data/*.md",
    "docs/*.md",
    "CASE_STUDY.md",
    "CHANGELOG.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "PRIVACY.md",
    "AGENTS.md",
    "scripts/build_annotation_pack.py",
    "scripts/migrate_gold_to_v2.py",
)
EXCLUDED = {LEDGER}

# One pattern per citation style found in the repository. Each has a `kind` group so
# the normaliser knows how to spell it. An article citation may continue as an
# enumeration or a range ("Art. 28(2) and 28(3)(d)", "Art. 44 to 49", "Articles 32 to
# 36"), and every member is extracted. Not recognised, because the repository does
# not use them: "Art 28" without a stop, "Sec. 311", "para." pinpoints.
_PINPOINT = r"\d+(?:\s?\(\d+\))*(?:\s?\([a-z]\))?"
_CONTINUATION = rf"(?:(?:,|\sand|\sto|\sthrough)\s(?:Arts?\.\s?|Articles?\s)?{_PINPOINT})*"
PATTERNS = (
    # Art. 28, Art. 28(3), Art. 28(3)(d), Art. 28 (3) (d), Arts. 44 to 49.
    re.compile(rf"(?P<art>Arts?\.\s?{_PINPOINT}{_CONTINUATION})"),
    re.compile(rf"(?<![A-Za-z])(?P<article>Articles?\s{_PINPOINT}{_CONTINUATION})", re.IGNORECASE),
    re.compile(r"(?P<chapter>Chapter\s[IVX]+)(?![A-Za-z])"),
    # § 130(1), §§ 130, 305 and 307 (an enumeration lists every number).
    re.compile(r"(?P<para>§§?\s?\d+(?:\(\d+\))?(?:(?:,\s?|\s(?:and|und)\s)\d+(?:\(\d+\))?)*)"),
    # "section 311 (1) of the German Civil Code (BGB)", possibly wrapped over a line.
    re.compile(r"(?P<section>section\s\d+\s*\(\d+\))", re.IGNORECASE),
    re.compile(r"(?P<regulation>Regulation \(EU\) \d{4}/\d+)"),
    re.compile(r"(?P<guidelines>Guidelines \d{2}/\d{4})"),
    re.compile(r"(?P<opinion>Opinion \d{1,2}/\d{4})"),
    # "lit. g", "lit. a to h", "lit. a through h": the DPA material's shorthand for
    # Art. 28(3) points.
    re.compile(r"(?P<lit>lit\.\s?[a-z]\)?(?:\s(?:to|through)\s[a-z]\)?)?)(?![a-z])"),
)


def _normalise(kind: str, text: str) -> list[str]:
    """Spell a raw citation the way the ledger's first column does."""
    text = " ".join(text.split())
    if kind in ("art", "article"):
        pinpoints = re.findall(_PINPOINT, text)
        return ["Art. " + re.sub(r"\s+\(", "(", pinpoint) for pinpoint in pinpoints]
    if kind == "chapter":
        return [text]
    if kind == "para":
        numbers = re.findall(r"\d+(?:\(\d+\))?", text)
        return [f"§ {number} BGB" for number in numbers]
    if kind == "section":
        number, subsection = re.match(r"section\s(\d+)\s*\((\d+)\)", text, re.IGNORECASE).groups()
        return [f"§ {number}({subsection}) BGB"]
    if kind == "lit":
        letters = re.findall(r"\b[a-z]\b", text.replace("lit.", ""))
        first, last = letters[0], letters[-1]
        return [f"Art. 28(3)({chr(code)})" for code in range(ord(first), ord(last) + 1)]
    return [text]


_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def extract_citations(text: str) -> list[str]:
    """Every normalised citation in `text`, in order of appearance, without duplicates.

    JSON escapes are decoded first: a file written with `ensure_ascii` spells the
    section sign as `\\u00a7`, which would otherwise hide every BGB citation in it.
    """
    text = _JSON_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)
    found: list[str] = []
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            kind = match.lastgroup
            assert kind is not None
            for citation in _normalise(kind, match.group(kind)):
                if citation not in found:
                    found.append(citation)
    return found


def ledger_provisions(markdown: str) -> list[str]:
    """The first cell of every table row of the ledger, backticks removed."""
    cells = []
    for line in markdown.splitlines():
        if not line.startswith("| "):
            continue
        first = line.split("|")[1].strip().replace("`", "")
        if first and first != "Instrument and provision" and not set(first) <= set("-: "):
            cells.append(first)
    return cells


def _pattern(citation: str) -> re.Pattern[str]:
    """`Art. 2` must not match `Art. 28`, nor `Chapter V` match `Chapter VI`; a bare
    `§ 130 BGB` is covered by `§ 130(1) BGB`."""
    bare = re.fullmatch(r"§ (\d+) BGB", citation)
    if bare:
        return re.compile(rf"§ {bare.group(1)}(?:\(\d+\))? BGB")
    if citation.startswith("Chapter "):
        return re.compile(re.escape(citation) + r"(?![IVX\d])")
    return re.compile(re.escape(citation) + r"(?!\d)")


def _covers(cell: str, citation: str) -> bool:
    return _pattern(citation).search(cell) is not None


def missing_from_ledger(citations: list[str], provisions: list[str]) -> list[str]:
    return [c for c in citations if not any(_covers(cell, c) for cell in provisions)]


def _scanned_files() -> list[Path]:
    files: set[Path] = set()
    for pattern in SCANNED_GLOBS:
        files.update(p for p in ROOT.glob(pattern) if p.is_file())
    return sorted(files - EXCLUDED)


def test_the_ledger_exists_with_the_expected_columns() -> None:
    text = LEDGER.read_text(encoding="utf-8")
    header = "| Instrument and provision | Used in | What the repo says | Current position | Official source | Verified on | Status |"
    assert header in text, "the ledger table must keep its columns"
    assert "## Watch list" in text


def test_every_ledger_row_is_dated_sourced_and_classified() -> None:
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| Instrument") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 7, line
        provision, _, _, _, source, verified_on, status = cells
        assert re.search(r"https://[^\s)]+", source), f"no official URL for {provision}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified_on), f"no verified-on date for {provision}"
        assert status in {"OK", "WATCH", "NEEDS OWNER REVIEW"}, f"unknown status for {provision}: {status}"


@pytest.mark.parametrize("path", _scanned_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_citation_in_harness_text_has_a_ledger_row(path: Path) -> None:
    citations = extract_citations(path.read_text(encoding="utf-8"))
    provisions = ledger_provisions(LEDGER.read_text(encoding="utf-8"))
    missing = missing_from_ledger(citations, provisions)
    assert not missing, (
        f"{path.relative_to(ROOT)} cites {missing} but docs/legal-currency.md has no row for them; "
        "add a dated, sourced row rather than deleting the citation"
    )


USED_IN = re.compile(r"`([\w./-]+\.(?:json|md|py)):(\d+(?:[-,]\d+)*)`(\s*\(context\))?")


def _ledger_rows(markdown: str) -> list[tuple[str, str]]:
    """(provision cell, used-in cell) for every table row of the ledger."""
    rows = []
    for line in markdown.splitlines():
        if not line.startswith("| ") or line.startswith("| Instrument") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append((cells[0].replace("`", ""), cells[1]))
    return rows


def _line_numbers(spec: str) -> list[int]:
    numbers: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            first, last = (int(n) for n in part.split("-"))
            numbers.extend(range(first, last + 1))
        else:
            numbers.append(int(part))
    return numbers


def test_used_in_references_point_at_the_citation() -> None:
    """A `file:line` pointer in the ledger names a line that carries the row's citation.

    Lines move when a file is edited above them; this fails as soon as a pointer no
    longer lands on the citation. A reference marked `(context)` names a line the row
    bears on without citing the provision, and is only checked to exist.
    """
    checked = 0
    for provision, used_in in _ledger_rows(LEDGER.read_text(encoding="utf-8")):
        for path, spec, context in USED_IN.findall(used_in):
            lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
            numbers = _line_numbers(spec)
            assert numbers and numbers[-1] <= len(lines), f"{provision}: {path}:{spec} is beyond the file"
            if context:
                continue
            referenced = "\n".join(lines[n - 1] for n in numbers)
            found = extract_citations(referenced)
            assert any(_covers(provision, c) for c in found), (
                f"ledger row {provision!r} points at {path}:{spec}, which cites {found or 'nothing'}"
            )
            checked += 1
    assert checked >= 40, checked


def test_the_scan_finds_the_known_gold_citations() -> None:
    """A scanner that silently found nothing would pass forever."""
    dpa = (ROOT / "expected" / "dpa.json").read_text(encoding="utf-8")
    found = extract_citations(dpa)
    for expected in ("Art. 28(3)(d)", "Art. 28(2)", "Art. 33(2)", "Chapter V", "Art. 46", "Regulation (EU) 2016/679"):
        assert expected in found, found
    nda = (ROOT / "expected" / "nda.json").read_text(encoding="utf-8")
    assert "§ 130(1) BGB" in extract_citations(nda)


def test_the_guard_bites_on_an_unlisted_citation() -> None:
    """Probe the extractor and the matcher on a string, not on a tracked file."""
    provisions = ledger_provisions(LEDGER.read_text(encoding="utf-8"))
    sample = (
        "Art. 28(3)(d) requires this; Article 99 and § 999(1) BGB and Chapter XIV, "
        "section 311 (1) of the German Civil Code (BGB), Guidelines 07/2020, lit. a to c."
    )
    citations = extract_citations(sample)
    assert citations == [
        "Art. 28(3)(d)", "Art. 99", "Chapter XIV", "§ 999(1) BGB", "§ 311(1) BGB",
        "Guidelines 07/2020", "Art. 28(3)(a)", "Art. 28(3)(b)", "Art. 28(3)(c)",
    ]
    assert missing_from_ledger(citations, provisions) == ["Art. 99", "Chapter XIV", "§ 999(1) BGB"]
    # Enumerations, ranges, spaced pinpoints and the long form keep every member.
    assert extract_citations("Art. 28(2) and 28(3)(d); Art. 44 to 49; Articles 32 to 36") == [
        "Art. 28(2)", "Art. 28(3)(d)", "Art. 44", "Art. 49", "Art. 32", "Art. 36",
    ]
    assert sorted(extract_citations("Article 28(10) and Art. 28 (3) (d), lit. a through c")) == sorted([
        "Art. 28(10)", "Art. 28(3)(d)", "Art. 28(3)(a)", "Art. 28(3)(b)", "Art. 28(3)(c)",
    ])
    # A chapter must not be covered by a longer chapter number.
    assert missing_from_ledger(["Chapter V"], ["Data Act Chapter VI"]) == ["Chapter V"]
    # A JSON file written with ensure_ascii escapes the section sign; it is still found.
    assert extract_citations('"see \\u00a7 999(1) BGB"') == ["§ 999(1) BGB"]
    # A number must not be matched as a prefix of a longer one.
    assert missing_from_ledger(["Art. 2"], ["GDPR Art. 28(2)"]) == ["Art. 2"]
    assert missing_from_ledger(["§ 130 BGB"], ["§ 130(1) BGB"]) == []
