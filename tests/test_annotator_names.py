"""Neither annotator's personal name may reappear in a tracked file.

Annotators are recorded by role label, from `contract_eval.annotators`. The names are
stored here only as salted SHA-256 digests of their normalised word forms, so this file
does not put them back. A digest keeps a name out of plain-text search; it is not
anonymisation, because a guess can be checked against it.

Annotator A also maintains the repository. The copyright notice, the citation metadata
and the action's author field name the maintainer rather than an annotation, so those
three files may carry that name, exactly as often as they do now. The maintainer's
account handle in URLs, the package metadata and the contact address is one joined word
and is deliberately not matched.
"""

import functools
import hashlib
import html
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SALT = "contract-eval/annotator-name-guard/v1:"

# Digest of SALT + one normalised word -> (annotator, which part of the name it is).
NAME_DIGESTS = {
    "98e132075881e22e2d41f1bcc5d8d4ceb66700b289f3c092745a9ecf70703f1d": ("Annotator A", "given name"),
    "03307d4c43d9649375a992200129ca62f69d017e9b7bb0ea5f685da26f45fdae": ("Annotator A", "family name"),
    "be587e747108eb019b2f179d51cb2cd6f91dc630f33d8329891118daf078d086": ("Annotator A", "family name"),
    "8313fe3b6885810a7247e03815227ebb477652bb292d3a2a430fc3ff6c324a06": ("Annotator A", "initial and family name"),
    "bb02e0dae0d6396bcad249d4c60b71a3072e9b3197e8d04edff75b71fcf0dc0a": ("Annotator A", "initial and family name"),
    "0f4cac8f432252bdde197bc29abe05f4c85702d8094f91c5fccaecea1b449818": ("Annotator A", "joined name"),
    "904e23994892082e82446741d3da49387ce0b0965964ff8fd9b51e793faef74c": ("Annotator A", "joined name"),
    "48b83e0f11789ba6ba825faf2a28ae3f8d56fb4759ef46e057b314562866a4fb": ("Annotator A", "joined name"),
    "ddd87758a93d50b4128ce3580353d6721c110d6f0a52abf483897ef0cdad1e8a": ("Annotator B", "given name"),
    "fab47f4a7fe3cd6981bf88d7a1be0c323962f54580e939d9ad5457e2f3256d79": ("Annotator B", "family name"),
    "27d9910ea7c48fb49b8a150a8b40763bdb811491ec837e17886139a3f8f3cdaf": ("Annotator B", "initial and family name"),
    "023ba5b5cf3f239c9d4f3d23f745b9393ef94f4d40d9b17829e85a74942d6f0e": ("Annotator B", "joined name"),
    "82c3fa9bac65bd1b890d9a415d13f26c7edc14fce498e205ffcf8f24ca11ce4c": ("Annotator B", "joined name"),
}

# Maintainer notices, not annotations: the number of name words each holds today.
ALLOWED = {
    ("LICENSE", "Annotator A"): 2,
    ("CITATION.cff", "Annotator A"): 2,
    ("action.yml", "Annotator A"): 2,
}

_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_WORD = re.compile(r"[a-z0-9]+")
_GERMAN = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})


@functools.lru_cache(maxsize=None)
def _digest(word: str) -> str:
    return hashlib.sha256((SALT + word).encode("utf-8")).hexdigest()


def _spellings(text: str) -> tuple[str, str]:
    """The text with JSON, URL and HTML escapes decoded, folded with umlauts as oe and as o."""
    decoded = html.unescape(unquote(_JSON_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)))
    folded = unicodedata.normalize("NFKC", decoded).casefold()
    stripped = "".join(c for c in unicodedata.normalize("NFKD", folded) if not unicodedata.combining(c))
    return folded.translate(_GERMAN), stripped


def name_hits(text: str) -> list[tuple[str, str]]:
    """Every word of either annotator's name in the text, as (annotator, part of the name)."""
    best: list[tuple[str, str]] = []
    for spelling in _spellings(text):
        hits = [NAME_DIGESTS[d] for d in map(_digest, _WORD.findall(spelling)) if d in NAME_DIGESTS]
        if len(hits) > len(best):
            best = hits
    return best


def _tracked_files() -> list[str]:
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    return [name for name in listing.decode("utf-8").split("\0") if name]


def test_no_tracked_file_carries_an_annotator_name():
    problems = []
    for name in _tracked_files():
        path = ROOT / name
        if not path.is_file():
            continue  # deleted in the working tree, so there is nothing left to read
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")  # a binary's metadata chunks are still plain text

        located = [("path", hit) for hit in name_hits(name)]
        for number, line in enumerate(text.splitlines(), start=1):
            located += [(f"line {number}", hit) for hit in name_hits(line)]

        for annotator in ("Annotator A", "Annotator B"):
            where = [f"{place} ({part})" for place, (who, part) in located if who == annotator]
            allowed = ALLOWED.get((name, annotator), 0)
            if len(where) != allowed:
                problems.append(f"{name}: {annotator}'s name {len(where)}x, expected {allowed}: {', '.join(where)}")

    assert not problems, "Use the role labels from contract_eval.annotators:\n" + "\n".join(problems)


def test_every_allowance_names_a_tracked_file():
    tracked = set(_tracked_files())
    assert {name for name, _ in ALLOWED} <= tracked


def test_the_matcher_sees_through_case_accents_and_escapes(monkeypatch):
    """A matcher that silently found nothing would pass forever. Probe it with an
    ordinary word in place of a name."""
    monkeypatch.setitem(NAME_DIGESTS, _digest("gruesse"), ("probe", "word"))
    monkeypatch.setitem(NAME_DIGESTS, _digest("grusse"), ("probe", "word"))

    for text in ("Grüße", "GRÜSSE", "Grüße", "Gr&uuml;&szlig;e", "Gr%C3%BC%C3%9Fe",
                 "Gr\\u00fc\\u00dfe", "gruesse", "path/grüße-file.json"):
        assert name_hits(text) == [("probe", "word")], text
    for text in ("Grußwort", "Grüßen", "begrüße"):
        assert name_hits(text) == [], text
