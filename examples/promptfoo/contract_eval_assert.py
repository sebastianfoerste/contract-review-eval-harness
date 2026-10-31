"""promptfoo assertion that scores a model's contract review with contract-eval.

promptfoo runs a `python` assertion by calling `get_assert(output, context)` and
accepts a bool, a float, or a GradingResult-style dict with `pass`, `score` and
`reason` (https://www.promptfoo.dev/docs/configuration/expected-outputs/python/).
`output` is the model's reply; `context["vars"]` holds the test's variables. Wire it
into a `promptfooconfig.yaml` at the repository root like this (`file://` paths
resolve from the config file's directory):

    tests:
      - vars:
          case: nda
        assert:
          - type: python
            value: file://examples/promptfoo/contract_eval_assert.py

The assertion passes unless the release policy decides `REJECT`. Its score is the
review's citation grounding, and its reason is the decision with the blockers and
review items. promptfoo itself is not a dependency of this repository; the Python
that runs this file needs `contract-eval` installed.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from contract_eval.api import Verdict, evaluate_review


def _unfenced(text: str) -> str:
    """The text inside a surrounding ``` fence, or the text itself."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def get_assert(output: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    case = ((context or {}).get("vars") or {}).get("case") or "nda"
    try:
        review = json.loads(_unfenced(output))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            path.write_text(json.dumps(review), encoding="utf-8")
            result = evaluate_review(path, case)
    except ValueError as exc:  # not JSON, or not a review: pydantic errors are ValueErrors
        return {"pass": False, "score": 0.0, "reason": f"could not score: {str(exc).splitlines()[0]}"}
    findings = ", ".join(result.blockers + result.review_items) or "no findings"
    return {
        "pass": result.verdict is not Verdict.REJECT,
        "score": result.scores["citation_grounding"],
        "reason": f"{result.verdict} on {case}: {findings}",
    }
