"""Gate your own contract-review tool with pytest.

Copy this file into your test suite and replace `my_reviewer` with a call to your
product. Installing contract-eval registers its pytest plugin, so nothing else is
needed:

    pip install "contract-eval @ git+https://github.com/sebastianfoerste/contract-review-eval-harness"
    pytest test_my_reviewer.py

`assert_review_passes` scores the review with the same code as `contract-eval score`
and fails the test with the release policy's reasons.
"""

from contract_eval import ReviewOutput, load_case
from contract_eval.models import Citation, Clause, RiskFlag
from contract_eval.pytest_plugin import assert_review_passes


def my_reviewer(contract_text: str) -> ReviewOutput:
    """Stand-in for your tool. Replace the body with a call to your product.

    This one cheats so the example passes: it copies the bundled answer set and quotes
    each clause's anchor, which is the review the release policy is looking for.
    """
    gold = load_case("nda").expected
    return ReviewOutput(
        clauses=[Clause(clause_type=name, text=name.replace("_", " ")) for name in gold.clause_types],
        risk_flags=[
            RiskFlag(clause_type=name, severity=severity, rationale=gold.severity_rationale[name])
            for name, severity in gold.risk_flags.items()
        ],
        citations=[Citation(quote=gold.clause_anchors[name], clause_type=name) for name in gold.clause_types],
    )


def test_nda_review_meets_the_release_policy(contract_case):
    case = contract_case("nda")
    assert_review_passes(my_reviewer(case.source_text), case)


def test_a_softer_gate_fails_only_on_reject():
    case = load_case("nda")
    result = assert_review_passes(my_reviewer(case.source_text), case, allow_human_review=True)
    assert result.scores["hallucination_count"] == 0
