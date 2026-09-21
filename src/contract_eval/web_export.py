"""One exporter for the bounded web dataset, evidence status and parity vectors."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Any

from contract_eval.cases import ALL_CASES
from contract_eval.cli import score_review
from contract_eval.models import ExpectedAnswer, ReviewOutput
from contract_eval.reference_evidence import digest, encoded, reference_status

SOURCE_PATHS = ["src", "data", "expected", "fixtures", "annotations", "pyproject.toml"]


def release_id(version: str) -> str:
    return re.sub(r"rc(\d+)$", r"-rc.\1", version)


def validate_source_commit(root: Path, commit: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Invalid harness source commit")
    subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=root, check=True, capture_output=True)
    changes = subprocess.check_output(["git", "diff", commit, "--", *SOURCE_PATHS], cwd=root)
    additions = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", *SOURCE_PATHS], cwd=root)
    if changes or additions:
        raise ValueError("Export inputs differ from the recorded commit. Commit the reviewed harness inputs before exporting.")


def build_web_snapshot(root: Path, *, source_commit: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    commit = source_commit or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    validate_source_commit(root, commit)
    reference = reference_status(root)
    if reference["stage"] == "invalid":
        raise ValueError(f"Reference evidence is invalid: {reference['errors']}")
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    cases, vectors = [], []
    titles = {"nda": "Mutual NDA", "saas": "SaaS agreement", "dpa": "Data processing agreement"}
    for case in ALL_CASES:
        paths = {"source": root / "data" / f"{case}_sample.md", "gold": root / "expected" / f"{case}.json", "review": root / "fixtures" / f"{case}_stub.json"}
        source = paths["source"].read_text(encoding="utf-8")
        gold = ExpectedAnswer.model_validate_json(paths["gold"].read_bytes())
        review = ReviewOutput.model_validate_json(paths["review"].read_bytes())
        cases.append({"id": case, "title": titles[case], "source": source, "gold": gold.model_dump(), "review": review.model_dump(),
                      "hashes": {name: digest(path.read_bytes()) for name, path in paths.items()}})
        for scenario in ("baseline", "no-evidence", "missed-risks", "conflicting-flags"):
            output = review.model_copy(deep=True)
            if scenario == "no-evidence": output.citations = []
            if scenario == "missed-risks": output.risk_flags = []
            if scenario == "conflicting-flags":
                first = output.risk_flags[0].model_copy(deep=True)
                first.severity = "low" if first.severity != "low" else "high"
                output.risk_flags.append(first)
            for aliases in ("on", "off"):
                vectors.append({"caseId": case, "scenario": scenario, "aliases": aliases,
                                "expected": score_review(source, gold, output, alias_mode=aliases)})
        for output in (ReviewOutput(clauses=[], risk_flags=[], citations=[]), review):
            vectors.append({"caseId": case, "customReview": output.model_dump(), "aliases": "on", "expected": score_review(source, gold, output)})
    payload = {"schema": "contract-eval.web-benchmark.v2", "version": version, "releaseId": release_id(version),
               "repository": "https://github.com/sebastianfoerste/contract-review-eval-harness", "sourceCommit": commit,
               "goldStatus": f"v1 reference answers; v2 evidence: {reference['stage']}", "scoringEdition": "v1",
               "referenceEvidence": reference, "cases": cases,
               "methodologyHashes": {path.relative_to(root).as_posix(): digest(path.read_bytes()) for path in sorted((root / "src/contract_eval").rglob("*.py"))}}
    payload["integritySha256"] = digest(encoded(payload))
    return payload, vectors


def write_web_snapshot(root: Path, web: Path) -> None:
    benchmark, vectors = build_web_snapshot(root)
    (web / "lib/benchmark.json").write_bytes(encoded(benchmark))
    (web / "tests/python-parity.json").write_bytes(encoded(vectors))


def check_web_snapshot(root: Path, web: Path) -> None:
    current = json.loads((web / "lib/benchmark.json").read_text())
    expected, vectors = build_web_snapshot(root, source_commit=current["sourceCommit"])
    if current != expected:
        raise ValueError("Web dataset, reference status or provenance differs from the canonical export")
    if json.loads((web / "tests/python-parity.json").read_text()) != vectors:
        raise ValueError("Web parity vectors differ from the complete canonical scenario set")
    package = json.loads((web / "package.json").read_text())
    if package["version"] != expected["releaseId"]:
        raise ValueError("Harness and web package release versions do not match")
