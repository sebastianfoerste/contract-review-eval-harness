from pathlib import Path

from contract_eval.adapters.stub import StubAdapter


def test_stub_returns_review_output_from_fixture():
    adapter = StubAdapter(fixtures_dir=Path("fixtures"))
    out = adapter.review(source_text="ignored", case="nda")
    assert len(out.clauses) >= 5
    assert any(f.severity == "high" for f in out.risk_flags)
    assert len(out.citations) >= 5
