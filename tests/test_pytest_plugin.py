"""The pytest plugin loads from its entry point and fails tests with the policy's reasons.

pytester runs a real inner pytest session, so these tests prove the `pytest11`
registration in pyproject.toml rather than an import.
"""

import shutil
from pathlib import Path

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "fixtures" / "nda_stub.json"


def test_the_fixture_is_available_without_a_conftest(pytester):
    pytester.makepyfile(
        """
        def test_fixture(contract_case):
            assert contract_case("nda").bundled
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)


def test_a_rejected_review_fails_with_the_blockers(pytester):
    pytester.makepyfile(
        f"""
        from contract_eval.pytest_plugin import assert_review_passes

        def test_stub():
            assert_review_passes({str(STUB)!r}, "nda")
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines([
        "*contract-eval: nda review is REJECT under contract-review-eval.strict-legal-release-policy.v2.1",
        "*blockers: citation_grounding_below_100_percent, unsupported_citation_detected",
    ])
    # The summary still lists the scored review after the failure.
    result.stdout.fnmatch_lines(["*= contract-eval =*", "REJECT nda: clause F1 0.96*"])


def test_the_regression_policy_applies_the_demo_thresholds(pytester):
    pytester.makepyfile(
        f"""
        from contract_eval.pytest_plugin import assert_review_passes

        def test_stub():
            result = assert_review_passes({str(STUB)!r}, "nda", policy="regression")
            assert result.verdict == "REJECT"
        """
    )

    pytester.runpytest().assert_outcomes(passed=1)


def test_the_plugin_can_be_disabled(pytester):
    pytester.makepyfile(
        """
        def test_fixture(contract_case):
            pass
        """
    )

    result = pytester.runpytest("-p", "no:contract_eval")

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*fixture 'contract_case' not found*"])


def test_the_copyable_example_passes(pytester):
    shutil.copy(ROOT / "examples" / "test_my_reviewer.py", pytester.path)

    result = pytester.runpytest("test_my_reviewer.py")

    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["PILOT_ELIGIBLE nda: clause F1 1.00*"])
