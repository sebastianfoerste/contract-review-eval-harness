"""Record document hashes and locate answer quotes for every matter.

An answer author writes the document id and the verbatim quote. This script finds the
quote, requires it to occur exactly once in that document, and records its offsets.
It also re-records the hash of any matter document that has changed.

Without --write it only reports, and exits non-zero if anything would change. Changing
a document's hash is a deliberate act: every answer anchored in it must be re-read.

    python scripts/matter_sync.py            # check
    python scripts/matter_sync.py --write    # apply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contract_eval.matter import MATTERS_DIR, file_sha256
from contract_eval.matter_scorer import find_whole
from contract_eval.scorer import build_normalized_index, normalize_text


def _dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sync_matter(directory: Path, root: Path, write: bool) -> tuple[list[str], list[str]]:
    changes: list[str] = []
    errors: list[str] = []
    manifest_path = directory / "matter.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    name = directory.name

    texts: dict[str, str] = {}
    for document in manifest["documents"]:
        path = root / document["path"]
        if not path.is_file():
            errors.append(f"{name}: missing document {document['path']}")
            continue
        texts[document["document_id"]] = path.read_text(encoding="utf-8")
        actual = file_sha256(path)
        if document.get("sha256") != actual:
            changes.append(f"{name}: hash of {document['document_id']}")
            document["sha256"] = actual

    # Nothing is written until the whole matter has been read without error. Recording
    # a new document hash while an answer still points at the old text would make the
    # matter load cleanly with an answer nobody can reach.
    pending: list[tuple[Path, dict]] = [(manifest_path, manifest)]
    indexes = {doc_id: build_normalized_index(text) for doc_id, text in texts.items()}

    for round_ in manifest["rounds"]:
        gold_path = directory / round_["expected"]
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        for issue in gold.get("issues", []):
            for span in issue.get("evidence", []):
                label = f"{name}/{round_['round_id']}/{issue.get('issue_id')}"
                text = texts.get(span.get("document_id"))
                if text is None:
                    errors.append(f"{label}: unknown document {span.get('document_id')!r}")
                    continue
                occurrences = text.count(span["quote"])
                if occurrences != 1:
                    errors.append(
                        f"{label}: quote occurs {occurrences} times in "
                        f"{span['document_id']}, must occur exactly once: {span['quote']!r}"
                    )
                    continue
                # A review's citation is matched after normalising case, punctuation
                # and spacing, so the passage has to be unique in that form too.
                normalised = find_whole(
                    indexes[span["document_id"]], normalize_text(span["quote"])
                )
                if len(normalised) != 1:
                    errors.append(
                        f"{label}: quote occurs {len(normalised)} times as whole words "
                        f"in {span['document_id']} once case and punctuation are "
                        f"ignored, must occur exactly once: {span['quote']!r}"
                    )
                    continue
                start = text.find(span["quote"])
                end = start + len(span["quote"])
                if (span.get("start"), span.get("end")) != (start, end):
                    changes.append(f"{label}: offsets in {span['document_id']}")
                    span["start"], span["end"] = start, end
        pending.append((gold_path, gold))

    if write and not errors:
        for path, data in pending:
            _dump(path, data)
    return changes, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=Path("."), type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    base = args.root / MATTERS_DIR
    directories = sorted(p for p in base.iterdir() if (p / "matter.json").is_file())
    changes: list[str] = []
    errors: list[str] = []
    for directory in directories:
        found, failed = sync_matter(directory, args.root, args.write)
        changes += found
        errors += failed

    for error in errors:
        print(f"ERROR: {error}")
    for change in changes:
        print(("updated: " if args.write and not errors else "out of date: ") + change)
    if errors:
        return 1
    if changes and not args.write:
        print("Run `python scripts/matter_sync.py --write` after reviewing the changes.")
        return 1
    print(f"matter sync {'applied' if changes else 'clean'} ({len(directories)} matters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
