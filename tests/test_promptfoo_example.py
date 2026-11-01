"""The promptfoo assertion example scores like the CLI and never needs promptfoo.

`examples/promptfoo/contract_eval_assert.py` is loaded from its path, as promptfoo
would load it, and called with the bundled NDA stub, which carries one fabricated
citation and is therefore a REJECT. Nothing here touches the network or imports
promptfoo.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ASSERTION = ROOT / "examples" / "promptfoo" / "contract_eval_assert.py"
STUB = ROOT / "fixtures" / "nda_stub.json"


@pytest.fixture(scope="module")
def get_assert():
    spec = importlib.util.spec_from_file_location("contract_eval_assert", ASSERTION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_assert


def test_stub_is_rejected_with_its_grounding_as_score(get_assert) -> None:
    result = get_assert(output=STUB.read_text(encoding="utf-8"), context={"vars": {"case": "nda"}})
    assert isinstance(result, dict)
    assert result["pass"] is False
    assert result["score"] == pytest.approx(8 / 9)
    assert "REJECT" in result["reason"]
    assert "unsupported_citation_detected" in result["reason"]


def test_fenced_json_output_is_accepted(get_assert) -> None:
    fenced = "```json\n" + STUB.read_text(encoding="utf-8") + "\n```"
    result = get_assert(output=fenced, context={"vars": {"case": "nda"}})
    assert result["pass"] is False
    assert result["score"] == pytest.approx(8 / 9)


def test_case_defaults_to_nda(get_assert) -> None:
    result = get_assert(output=STUB.read_text(encoding="utf-8"), context={"vars": {}})
    assert "REJECT on nda" in result["reason"]


def test_output_that_is_not_a_review_fails_with_a_reason(get_assert) -> None:
    for output in ("not json", '{"clauses": "nope"}'):
        result = get_assert(output=output, context={})
        assert result["pass"] is False
        assert result["score"] == 0.0
        assert result["reason"].startswith("could not score")
