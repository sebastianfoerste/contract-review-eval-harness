"""The quickstart notebook is valid, ships without outputs, and runs offline as written."""

import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "examples" / "quickstart.ipynb"
COLAB_URL = (
    "https://colab.research.google.com/github/sebastianfoerste/"
    "contract-review-eval-harness/blob/main/examples/quickstart.ipynb"
)


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _source(cell: dict) -> str:
    source = cell["source"]
    return "".join(source) if isinstance(source, list) else source


def test_notebook_is_nbformat_4_with_a_colab_badge(notebook):
    assert notebook["nbformat"] == 4
    assert notebook["cells"][0]["cell_type"] == "markdown"
    assert COLAB_URL in _source(notebook["cells"][0])
    assert all(cell["cell_type"] in {"markdown", "code"} for cell in notebook["cells"])


def test_no_outputs_are_stored(notebook):
    # Stored outputs go stale silently and leak whatever the author's machine printed.
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == []
            assert cell["execution_count"] is None


def test_code_cells_run_in_order_offline(notebook, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("the quickstart must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.chdir(ROOT)

    namespace: dict = {}
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        # Shell and magic lines (the %pip install) are Jupyter-only; the package is
        # already installed here.
        lines = [line for line in _source(cell).splitlines() if not line.lstrip().startswith(("%", "!"))]
        exec(compile("\n".join(lines), f"quickstart.ipynb[{index}]", "exec"), namespace)

    printed = capsys.readouterr().out
    assert "verdict: REJECT" in printed
    assert "verdict: REJECT -> HUMAN_REVIEW_REQUIRED" in printed
    assert "hallucination_count: 1 -> 0" in printed
