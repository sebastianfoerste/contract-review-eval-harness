"""Export the annotation pack as a standalone bundle for the second annotator.

Blindness here is procedural, not technical. The harness repository is public, and the
pack lives one directory from the gold set, so anything handed to an annotator relies
on them not going looking. This export does what it can to avoid handing them a map:

- The exclusion list names categories, not the paths that hold them. The repository
  copy keeps the detailed list, because there it is an audit record rather than a hint.
- The guideline asks the annotator not to search for source material, without naming
  where it lives.

What it cannot hide: the schema identifiers embedded in the templates carry the
project name, and the contracts themselves are public, so a determined search reaches
the gold set. That limitation is disclosed rather than papered over, and it travels
with the agreement statistics.
"""

import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.capture import canonical_sha256, text_sha256  # noqa: E402

PACK = ROOT / "annotations" / "pack"
OUT = ROOT / "annotations" / "bundle"

# Categories only. The repository manifest keeps the path-level detail.
WITHHELD = [
    "the existing authoritative answer set",
    "the first annotator's candidate obligations, severities and rationales",
    "the first annotator's vocabulary and synonym choices",
    "all model output",
    "all computed scores, certificates and campaign results",
    "the maintainer's internal annotation guideline",
]

INSTRUCTIONS = (
    "Work only from the contracts and the guideline in this bundle. Please do not "
    "search for these documents or any related project online, and do not consult any "
    "other annotation of them, before returning your work. The value of this exercise "
    "depends entirely on your reading being independent."
)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    staging = OUT / "annotation-pack"
    staging.mkdir(parents=True)

    files: dict[str, str] = {}
    for source in sorted(PACK.rglob("*")):
        if not source.is_file() or source.name == "MANIFEST.json":
            continue
        relative = source.relative_to(PACK)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)

        text = source.read_text(encoding="utf-8")
        if relative.name == "ANNOTATOR_GUIDELINE.md":
            text = text.replace(
                "Work only from the contracts and this guideline. Do not consult the "
                "repository, any\nmodel output, or anyone else's annotation of these "
                "documents before you return yours.",
                "Work only from the contracts and this guideline. Please do not search "
                "for these\ndocuments online, and do not consult anyone else's "
                "annotation of them, before you\nreturn yours. The value of this "
                "exercise depends entirely on your reading being\nindependent.",
            )
        target.write_text(text, encoding="utf-8")
        files[str(relative)] = text_sha256(text)

    manifest = {
        "schema": "contract-review-eval.annotation-pack.v1",
        "pack_id": "blind-annotation-2026-09-03",
        "annotator": "annotator-b",
        "files": dict(sorted(files.items())),
        "withheld": WITHHELD,
        "instructions": INSTRUCTIONS,
        "blindness": (
            "Procedural, not technical. The reviewer is asked not to seek out the "
            "source material; nothing prevents it. Any agreement statistic computed "
            "from this annotation carries that limitation."
        ),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    (staging / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    archive = OUT / "annotation-pack.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(OUT))

    print(f"bundle: {archive.relative_to(ROOT)} ({archive.stat().st_size} bytes)")
    print(f"  {len(files) + 1} files, manifest {manifest['manifest_sha256'][:16]}")
    print(f"  {len(WITHHELD)} categories withheld, named without paths")
    print("\nNOT SENT. Hand to the reviewer yourself; blindness is procedural.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
