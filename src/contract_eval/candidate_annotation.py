"""Blind annotation for the native My Counsel candidate track.

The annotator works with paragraph numbers and playbook IDs and never edits a hash. The
compiler turns a filled annotation into the hash-bound `mycounsel.candidate-reference.v1`
that `candidates.py` scores against. The matching rule is written in the guideline
shipped with the pack and applied in `candidates.evaluate_candidates`, so a reference
written six months from now is keyed the same way as one written today.

One annotation is one reading: this module compiles it to a DRAFT reference and nothing
more. A reference may be called independently reviewed only after two blind annotations
and written adjudication (`candidate_adjudication`).

Nothing here decides legal adequacy. A compiled reference says which playbook entries a
reviewer expected to see raised and where; it does not grade an explanation or an
amendment.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract_eval.candidates import (
    CandidateReference,
    Playbook,
    anchor_id,
    digest,
    document_paragraphs,
)

ANNOTATION_SCHEMA = "mycounsel.candidate-annotation.v1"
PACK_SCHEMA = "mycounsel.annotation-pack.v1"
CORPUS_SCHEMA = "mycounsel.synthetic-corpus.v1"
REFERENCE_SCHEMA = "mycounsel.candidate-reference.v1"
SOURCE_REGISTER_SCHEMA = "mycounsel.source-register.v1"
HEX64 = r"^[a-f0-9]{64}$"
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# Files that hold what a person wrote. A derived file is never written over one of them.
WRITTEN_INPUT_SCHEMAS = (ANNOTATION_SCHEMA, "mycounsel.candidate-adjudication.v1")
# Where a corpus keeps the guideline its annotators work from.
GUIDELINE_PATH = Path("annotation") / "GUIDELINE.md"
SNAPSHOT_BODY_SEPARATOR = "\n---\n"

# Withheld from the pack, by category. The manifest lists them so the exclusion can be
# audited; tests/test_candidate_annotation.py checks the pack against the withheld files.
WITHHELD = [
    "replay-run.json (hand-authored demonstration findings)",
    "replay-score.json (the evaluator's output for that replay)",
    "README.md of the corpus (describes how the variants were constructed)",
    "build_fixtures.py (constructs the variants)",
    "any model output, experiment report or earlier annotation",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CorpusDocument(Strict):
    variant: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    filename: str = Field(pattern=r"^[a-z0-9-]+\.docx$")
    sha256: str = Field(pattern=HEX64)


class Corpus(Strict):
    schema_: Literal["mycounsel.synthetic-corpus.v1"] = Field(alias="schema")
    corpusKind: Literal["SYNTHETIC"]
    referenceStatus: str
    documents: list[CorpusDocument] = Field(min_length=1)
    playbooks: dict[str, str]
    instructions: str

    def document(self, variant: str) -> CorpusDocument:
        for entry in self.documents:
            if entry.variant == variant:
                return entry
        raise ValueError(f"unknown corpus variant {variant}")


def load_corpus(corpus_dir: Path) -> Corpus:
    """Read the corpus manifest and verify every pinned file against it."""
    corpus = Corpus.model_validate_json((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    if len({d.variant for d in corpus.documents}) != len(corpus.documents):
        raise ValueError("corpus variants must be unique")
    for document in corpus.documents:
        if digest((corpus_dir / document.filename).read_bytes()) != document.sha256:
            raise ValueError(f"corpus document {document.filename} does not match its manifest hash")
    for name, expected in corpus.playbooks.items():
        if digest((corpus_dir / f"{name}.json").read_bytes()) != expected:
            raise ValueError(f"corpus playbook {name} does not match its manifest hash")
    return corpus


class Source(Strict):
    id: str = Field(pattern=r"^SRC-[A-Z0-9-]{1,40}$")
    instrument: str
    provision: str
    language: str
    edition: str
    url: str = Field(pattern=r"^https?://")
    fetchedAt: str
    snapshot: str = Field(pattern=r"^sources/[A-Za-z0-9._-]+$")
    # Hash of the provision text in the snapshot, without the header above the separator.
    snapshotTextSha256: str = Field(pattern=HEX64)
    status: Literal["FETCHED_NOT_LAWYER_REVIEWED", "SOURCE_CHECKED_NOT_LAWYER_REVIEWED", "LAWYER_REVIEWED"]
    currentTextChecked: bool
    currentTextNote: str
    usedBy: list[str] = Field(min_length=1)
    pinpoints: dict[str, str]
    applicabilityAssumptions: list[str]
    notCovered: list[str] = Field(default_factory=list)
    reviewedOn: str | None = None


class SourceRegister(Strict):
    schema_: Literal["mycounsel.source-register.v1"] = Field(alias="schema")
    sources: list[Source] = Field(min_length=1)


def snapshot_text(raw: str) -> str:
    """The provision text of a snapshot file: everything below the header separator."""
    if SNAPSHOT_BODY_SEPARATOR not in raw:
        raise ValueError("snapshot has no header separator")
    return raw.split(SNAPSHOT_BODY_SEPARATOR, 1)[1].rstrip("\n")


def load_source_register(corpus_dir: Path) -> SourceRegister | None:
    """Read the source register, if the corpus has one, and hold it to what it claims.

    Every snapshot must hash to its registered value, every entry the register cites must
    exist in a playbook with a pinpoint, and every statutory playbook entry must be covered
    by a source. A register that lags the playbook is refused, not copied.
    """
    path = corpus_dir / "sources.json"
    if not path.exists():
        return None
    register = SourceRegister.model_validate_json(path.read_text(encoding="utf-8"))
    corpus = load_corpus(corpus_dir)
    entries = {}
    for name in corpus.playbooks:
        book = Playbook.model_validate_json((corpus_dir / f"{name}.json").read_text(encoding="utf-8"))
        entries.update({entry.id: entry for entry in book.entries})
    covered: set[str] = set()
    for source in register.sources:
        raw = (corpus_dir / source.snapshot).read_text(encoding="utf-8")
        if digest(snapshot_text(raw)) != source.snapshotTextSha256:
            raise ValueError(f"snapshot {source.snapshot} does not match the hash registered for {source.id}")
        unknown = sorted(set(source.usedBy) - entries.keys())
        if unknown:
            raise ValueError(f"source {source.id} is cited for unknown playbook entries: {', '.join(unknown)}")
        if set(source.pinpoints) != set(source.usedBy) or any(not p.strip() for p in source.pinpoints.values()):
            raise ValueError(f"source {source.id} needs exactly one pinpoint per citing playbook entry")
        covered.update(source.usedBy)
    statutory = {entry_id for entry_id, entry in entries.items() if entry.category == "STATUTORY_REQUIREMENT"}
    uncovered = sorted(statutory - covered)
    if uncovered:
        raise ValueError("statutory playbook entries without a registered source: " + ", ".join(uncovered))
    return register


def corpus_bindings(corpus_dir: Path) -> dict[str, str | None]:
    """The three hashes that tie an annotation to the material it was made from."""
    load_source_register(corpus_dir)
    register = corpus_dir / "sources.json"
    return {
        "corpusManifestSha256": digest((corpus_dir / "manifest.json").read_bytes()),
        "guidelineSha256": digest((corpus_dir / GUIDELINE_PATH).read_bytes()),
        "sourceRegisterSha256": digest(register.read_bytes()) if register.exists() else None,
    }


class AnnotatedIssue(Strict):
    playbookReference: str = Field(min_length=1, max_length=200)
    # Zero-based paragraph number from the pack's listing; None for a missing clause.
    paragraph: int | None = Field(default=None, ge=0)
    missingClause: bool
    rationale: str = Field(min_length=1, max_length=5000)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]

    @model_validator(mode="after")
    def shape(self) -> "AnnotatedIssue":
        if self.missingClause != (self.paragraph is None):
            raise ValueError("a missing clause has no paragraph; an existing-clause issue names exactly one")
        if not self.rationale.strip():
            raise ValueError("an expected issue needs a written rationale")
        return self


class Annotation(Strict):
    schema_: Literal["mycounsel.candidate-annotation.v1"] = Field(alias="schema")
    variant: str
    playbook: str
    # Binding fields, filled by the pack builder. An annotator leaves them unchanged.
    documentSha256: str = Field(pattern=HEX64)
    playbookSha256: str = Field(pattern=HEX64)
    corpusManifestSha256: str = Field(pattern=HEX64)
    guidelineSha256: str = Field(pattern=HEX64)
    sourceRegisterSha256: str | None = Field(pattern=HEX64)
    # Filled by the annotator: the label agreed with the maintainer, not a name.
    annotator: str = ""
    annotatedOn: str = ""
    # The annotator attests this; None means not yet answered.
    sawModelOutput: bool | None = None
    issues: list[AnnotatedIssue] = Field(default_factory=list, max_length=200)
    uncertainties: str = ""

    @model_validator(mode="after")
    def consistent(self) -> "Annotation":
        keys = [(i.playbookReference, i.paragraph, i.missingClause) for i in self.issues]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate expected issue")
        missing = {i.playbookReference for i in self.issues if i.missingClause}
        located = {i.playbookReference for i in self.issues if not i.missingClause}
        both = sorted(missing & located)
        if both:
            # The guideline's tie-break: anchor to a paragraph whenever one deals with the
            # entry's subject, and call a clause missing only when none does.
            raise ValueError("an entry cannot be both missing and located at a paragraph: " + ", ".join(both))
        if self.annotatedOn:
            # The shape first: fromisoformat alone also accepts 20261012 and 2026-W41-1.
            if not ISO_DAY.fullmatch(self.annotatedOn):
                raise ValueError("annotatedOn must be an ISO date")
            try:
                date.fromisoformat(self.annotatedOn)
            except ValueError as error:
                raise ValueError("annotatedOn must be an ISO date") from error
        return self


def require_filled(annotation: Annotation) -> None:
    """Refuse an untouched or half-filled template; an empty issue list is otherwise a claim."""
    if not annotation.annotator.strip():
        raise ValueError("the annotation names no annotator; it looks like an unfilled template")
    if not annotation.annotatedOn:
        raise ValueError("the annotation has no date")
    if annotation.sawModelOutput is None:
        raise ValueError("the annotation does not answer whether model output was seen")


def resolve_anchors(annotation: Annotation, corpus_dir: Path,
                    located: list[tuple[str, int | None]]) -> list[str | None]:
    """Recorder anchors for (playbook entry, paragraph) pairs under one annotation's binding.

    Shared by the single-annotation compiler and by adjudication between two annotations
    (candidate_adjudication), so a paragraph number becomes an anchor in exactly one way.
    Refuses an annotation made from other material than the corpus now holds (document,
    playbook, business instructions and variants through the manifest, guideline, source
    register), an unknown playbook entry and a paragraph outside the document. A pair
    without a paragraph is a missing clause and has no anchor.
    """
    corpus = load_corpus(corpus_dir)
    document = corpus.document(annotation.variant)
    if document.sha256 != annotation.documentSha256:
        raise ValueError("annotation is bound to a different document")
    if corpus.playbooks.get(annotation.playbook) != annotation.playbookSha256:
        raise ValueError("annotation is bound to a different playbook")
    for name, current in corpus_bindings(corpus_dir).items():
        if getattr(annotation, name) != current:
            raise ValueError(f"annotation was made from a different pack: {name} no longer matches the corpus")
    book = Playbook.model_validate_json((corpus_dir / f"{annotation.playbook}.json").read_text(encoding="utf-8"))
    entries = {entry.id for entry in book.entries}
    paragraphs = document_paragraphs((corpus_dir / document.filename).read_bytes())
    anchors: list[str | None] = []
    for playbook_reference, paragraph in located:
        if playbook_reference not in entries:
            raise ValueError(f"unknown playbook entry {playbook_reference}")
        if paragraph is not None and paragraph >= len(paragraphs):
            raise ValueError(f"paragraph {paragraph} is outside the document")
        anchors.append(None if paragraph is None
                       else anchor_id(document.sha256, paragraph, paragraphs[paragraph]))
    return anchors


def reference_provenance(route: Literal["SINGLE_ANNOTATION", "ADJUDICATED"], annotations: list[Annotation],
                         low_confidence_issues: int) -> dict:
    """Provenance block of a compiled reference. All contributing annotations share one binding."""
    first = annotations[0]
    return {
        "route": route,
        "corpusManifestSha256": first.corpusManifestSha256,
        "guidelineSha256": first.guidelineSha256,
        "sourceRegisterSha256": first.sourceRegisterSha256,
        "lowConfidenceIssues": low_confidence_issues,
        "uncertaintiesRecorded": any(a.uncertainties.strip() for a in annotations),
        "annotatorSawModelOutput": any(a.sawModelOutput is not False for a in annotations),
    }


def compile_reference(annotation: Annotation, corpus_dir: Path, *, annotation_sha256: str) -> dict:
    """Resolve paragraph numbers to recorder anchors and emit a DRAFT candidate reference."""
    require_filled(annotation)
    anchors = resolve_anchors(annotation, corpus_dir,
                              [(issue.playbookReference, issue.paragraph) for issue in annotation.issues])
    reference = {
        "schema": REFERENCE_SCHEMA,
        # Equal to the corpus document hash: resolve_anchors refused anything else.
        "sourceSha256": annotation.documentSha256,
        "playbookSha256": annotation.playbookSha256,
        "status": "DRAFT",
        "reviewerEvidence": f"single annotation; annotation-sha256:{annotation_sha256}",
        "issues": [{
            "playbookReference": issue.playbookReference,
            "anchorId": anchor,
            "missingClause": issue.missingClause,
            "rationale": f"Confidence {issue.confidence}: {issue.rationale.strip()}",
        } for issue, anchor in zip(annotation.issues, anchors)],
        "provenance": reference_provenance(
            "SINGLE_ANNOTATION", [annotation], sum(issue.confidence == "LOW" for issue in annotation.issues)),
    }
    CandidateReference.model_validate(reference)
    return reference


def build_pack(corpus_dir: Path, out: Path, guideline: Path | None = None) -> dict:
    """Write the blind pack: guideline, numbered paragraphs, playbooks, sources, templates."""
    guideline = guideline or corpus_dir / GUIDELINE_PATH
    corpus = load_corpus(corpus_dir)
    bindings = corpus_bindings(corpus_dir)
    if digest(guideline.read_bytes()) != bindings["guidelineSha256"]:
        raise ValueError(f"the pack is built from the corpus guideline at {corpus_dir / GUIDELINE_PATH}")
    if out.exists():
        if not out.is_dir():
            raise FileExistsError(f"refusing to replace {out}: it is not a folder")
        if any(out.iterdir()):
            # An older pack is rebuilt in place. Anything else, for example a folder of
            # returned annotations, is somebody's work and stays.
            try:
                is_pack = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8")).get("schema") == PACK_SCHEMA
            except (OSError, ValueError, AttributeError):
                is_pack = False
            if not is_pack:
                raise FileExistsError(f"refusing to replace {out}: it holds files and is not an annotation pack")
            for template in sorted((out / "templates").glob("*.json")):
                try:
                    filled = json.loads(template.read_text(encoding="utf-8"))
                except ValueError:
                    filled = {"issues": ["unreadable"]}
                if any(filled.get(name) for name in ("annotator", "annotatedOn", "issues", "uncertainties")) \
                        or filled.get("sawModelOutput") is not None:
                    raise FileExistsError(
                        f"refusing to rebuild {out}: {template.name} has been filled in; "
                        "move returned annotations out of the pack folder first")
        shutil.rmtree(out)
    for folder in ("documents", "playbooks", "templates", "sources"):
        (out / folder).mkdir(parents=True)
    files: dict[str, str] = {}

    def put(relative: str, text: str) -> None:
        (out / relative).write_text(text, encoding="utf-8")
        files[relative] = digest(text)

    def copy(source: Path, relative: str) -> None:
        shutil.copyfile(source, out / relative)
        files[relative] = digest(source.read_bytes())

    put("GUIDELINE.md", guideline.read_text(encoding="utf-8"))
    put("instructions.md", "# Business instructions\n\n" + corpus.instructions + "\n")
    for document in corpus.documents:
        paragraphs = document_paragraphs((corpus_dir / document.filename).read_bytes())
        lines = [
            f"# {document.filename}", "", f"SHA-256 {document.sha256}", "",
            "Paragraph numbers start at 0. In a template, enter the number only: 2 for P2.", "",
        ]
        lines += [f"P{index}: {text}" for index, text in enumerate(paragraphs)]
        put(f"documents/{document.variant}.paragraphs.md", "\n".join(lines) + "\n")
        copy(corpus_dir / document.filename, f"documents/{document.filename}")
    for name, book_hash in corpus.playbooks.items():
        raw = (corpus_dir / f"{name}.json").read_text(encoding="utf-8")
        book = Playbook.model_validate_json(raw)
        lines = [f"# Playbook {name}", "", f"SHA-256 {book_hash}", "",
                 "| ID | Category | Requirement |", "| --- | --- | --- |"]
        lines += [f"| {e.id} | {e.category} | {e.requirement} |" for e in book.entries]
        put(f"playbooks/{name}.md", "\n".join(lines) + "\n")
        put(f"playbooks/{name}.json", raw)
        for document in corpus.documents:
            template = Annotation.model_validate({
                "schema": ANNOTATION_SCHEMA, "variant": document.variant, "playbook": name,
                "documentSha256": document.sha256, "playbookSha256": book_hash, **bindings,
            })
            put(f"templates/{document.variant}-{name}.annotation.json",
                json.dumps(template.model_dump(by_alias=True), indent=2, ensure_ascii=False) + "\n")
    register = load_source_register(corpus_dir)
    if register is not None:
        copy(corpus_dir / "sources.json", "sources/sources.json")
        for source in register.sources:
            copy(corpus_dir / source.snapshot, source.snapshot)
    manifest = {
        "schema": PACK_SCHEMA,
        **bindings,
        "files": dict(sorted(files.items())),
        "withheld": WITHHELD,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def verify_pack(out: Path, corpus_dir: Path | None = None) -> dict:
    """Recompute every listed hash and, given the corpus, prove the pack is current.

    Against its own manifest a pack only shows that nothing was added, removed or edited
    without the manifest line. A file edited together with its manifest line, or a pack
    built before the guideline, a playbook or the register changed, passes that check.
    With the corpus the pack is rebuilt in a scratch directory and must be identical.
    """
    manifest_bytes = (out / "MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=_no_repeated_keys)
    if manifest.get("schema") != PACK_SCHEMA:
        raise ValueError("not an annotation pack manifest")
    listed = set(manifest["files"])
    present = {p.relative_to(out).as_posix() for p in out.rglob("*")
               if p.is_file() and p.name != ".DS_Store" and p.relative_to(out).as_posix() != "MANIFEST.json"}
    if listed != present:
        raise ValueError(f"pack files differ from the manifest: {sorted(listed ^ present)}")
    for relative, expected in manifest["files"].items():
        if digest((out / relative).read_bytes()) != expected:
            raise ValueError(f"pack file {relative} differs from its manifest hash")
    if corpus_dir is not None:
        with tempfile.TemporaryDirectory() as scratch:
            build_pack(corpus_dir, Path(scratch) / "pack")
            fresh_bytes = (Path(scratch) / "pack" / "MANIFEST.json").read_bytes()
        # Bytes, not parsed values: a manifest can carry text a parser drops and a reader sees.
        if fresh_bytes != manifest_bytes:
            raise ValueError("the pack is not what the corpus builds today; rebuild it with make candidate-pack")
    return manifest


def _no_repeated_keys(pairs: list[tuple[str, object]]) -> dict:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("pack manifest repeats a key")
    return dict(pairs)


def bundle_pack(pack: Path, out: Path, corpus_dir: Path) -> str:
    """Zip a verified, current pack for sending. Fixed timestamps and order, so the hash is stable."""
    from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

    manifest = verify_pack(pack, corpus_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, "w") as archive:
        for relative in ["MANIFEST.json", *sorted(manifest["files"])]:
            info = ZipInfo(f"annotation-pack/{relative}", (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (pack / relative).read_bytes())
    return digest(out.read_bytes())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    corpus_default = Path("candidates/mycounsel")
    bundle = sub.add_parser("bundle", help="zip the verified, current pack for sending to an annotator")
    bundle.add_argument("--corpus", type=Path, default=corpus_default)
    bundle.add_argument("--pack", type=Path, default=corpus_default / "annotation-pack")
    bundle.add_argument("--out", type=Path,
                        default=corpus_default / "annotation-bundle" / "mycounsel-annotation-pack.zip")
    build = sub.add_parser("build", help="write the blind annotation pack")
    build.add_argument("--corpus", type=Path, default=corpus_default)
    build.add_argument("--out", type=Path, default=corpus_default / "annotation-pack")
    verify = sub.add_parser("verify", help="recompute the pack's hashes and prove it matches the corpus")
    verify.add_argument("--corpus", type=Path, default=corpus_default)
    verify.add_argument("--pack", type=Path, default=corpus_default / "annotation-pack")
    check = sub.add_parser("check", help="validate a filled annotation without writing a reference")
    check.add_argument("annotation", type=Path)
    check.add_argument("--corpus", type=Path, default=corpus_default)
    compile_ = sub.add_parser("compile", help="turn one filled annotation into a hash-bound DRAFT reference")
    compile_.add_argument("annotation", type=Path)
    compile_.add_argument("--corpus", type=Path, default=corpus_default)
    compile_.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "build":
        manifest = build_pack(args.corpus, args.out)
        print(f"Wrote {len(manifest['files'])} pack files to {args.out}. Withheld: {len(WITHHELD)} categories.")
        return
    if args.cmd == "verify":
        manifest = verify_pack(args.pack, args.corpus)
        print(f"Pack verified: {len(manifest['files'])} files match their hashes and the corpus.")
        return
    if args.cmd == "bundle":
        print(f"Wrote {args.out} (SHA-256 {bundle_pack(args.pack, args.out, args.corpus)}).")
        return
    raw = args.annotation.read_bytes()
    annotation = Annotation.model_validate_json(raw.decode("utf-8"))
    reference = compile_reference(annotation, args.corpus, annotation_sha256=digest(raw))
    count = len(reference["issues"])
    if args.cmd == "check":
        print(f"Annotation by {annotation.annotator.strip()} is valid: {count} expected issues"
              + (" (the annotator found nothing to raise)." if not count else "."))
        return
    text = json.dumps(reference, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        if args.out.exists() and any(schema.encode("utf-8") in args.out.read_bytes()
                                     for schema in WRITTEN_INPUT_SCHEMAS):
            raise FileExistsError(f"refusing to overwrite {args.out}: it is an annotation or an adjudication record")
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote DRAFT reference to {args.out}. Independent review needs a second annotation and adjudication.")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
