"""The JSON Schemas a tool targets to be scored by `contract-eval score`.

The Pydantic models are the single definition of a review and of an answer set. These
schemas are generated from them so a tool written in any language can validate its
output before it is scored, and the committed copies under `schemas/` are checked
against the models so the published contract cannot drift from the one enforced.

JSON Schema cannot express the cross-field rules `ExpectedAnswer` enforces, such as one
severity rationale per risk flag, so the answer-set schema says so in `$comment`. A
document can pass the schema and still be rejected by `contract-eval score`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from contract_eval.models import ExpectedAnswer, ReviewOutput

SCHEMA_DIRECTORY = "schemas"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_BASE_URL = (
    "https://raw.githubusercontent.com/sebastianfoerste/contract-review-eval-harness/main/schemas"
)

_ANSWER_SET_RULES = (
    "Also enforced when the answer set is loaded, beyond this schema: unique clause types; "
    "risk flags only for declared clause types; exactly one non-blank severity_rationale "
    "entry per risk flag; when clause_anchors is present, exactly one anchor per clause "
    "type; aliases must target a declared clause type and must not shadow one."
)

SCHEMAS: dict[str, tuple[type[BaseModel], str | None]] = {
    "review-output.schema.json": (ReviewOutput, None),
    "expected-answer.schema.json": (ExpectedAnswer, _ANSWER_SET_RULES),
}


def schema_document(file_name: str) -> dict[str, Any]:
    model, comment = SCHEMAS[file_name]
    document: dict[str, Any] = {
        "$schema": SCHEMA_DIALECT,
        "$id": f"{SCHEMA_BASE_URL}/{file_name}",
    }
    if comment:
        document["$comment"] = comment
    document.update(model.model_json_schema())
    return document


def encoded(file_name: str) -> str:
    return json.dumps(schema_document(file_name), indent=2, ensure_ascii=False) + "\n"


def write_schemas(root: Path) -> list[Path]:
    directory = root / SCHEMA_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for file_name in SCHEMAS:
        path = directory / file_name
        path.write_text(encoded(file_name), encoding="utf-8")
        written.append(path)
    return written


def schema_drift(root: Path) -> list[str]:
    """The committed schema files that no longer match the models; empty when in sync."""
    drifted = []
    for file_name in SCHEMAS:
        path = root / SCHEMA_DIRECTORY / file_name
        if not path.is_file() or path.read_text(encoding="utf-8") != encoded(file_name):
            drifted.append(f"{SCHEMA_DIRECTORY}/{file_name}")
    return drifted
