"""pytest integration: gate your own contract reviewer inside a test suite.

Installing contract-eval registers this module under the `pytest11` entry point, so
no conftest is needed:

    from contract_eval.pytest_plugin import assert_review_passes

    def test_my_reviewer_on_the_nda(contract_case):
        case = contract_case("nda")
        assert_review_passes(my_reviewer(case.source_text), case)

`assert_review_passes` scores with the same code as `contract-eval score` and fails
the test with the policy's reasons. The `contract_case` fixture is `load_case`. After
the run, a `contract-eval` section lists every review the plugin scored. Disable the
plugin with `-p no:contract_eval`.
"""

from __future__ import annotations

import os
from os import PathLike
from typing import Any

import pytest

from contract_eval.api import (
    REGRESSION_POLICY_ID,
    Case,
    ReviewResult,
    evaluate_review,
    load_case,
)
from contract_eval.models import ReviewOutput
from contract_eval.release_certificate import POLICY_ID

_RESULTS = pytest.StashKey[list[tuple[str, ReviewResult]]]()
# Configs of the sessions in progress, innermost last. A stack rather than one value
# because pytest can run a session inside another (pytester does).
_ACTIVE: list[pytest.Config] = []


def assert_review_passes(
    review: ReviewOutput | dict[str, Any] | str | PathLike[str],
    case: Case | str,
    *,
    policy: str = "release",
    allow_human_review: bool = False,
    alias_mode: str = "on",
) -> ReviewResult:
    """Fail the calling test unless `review` passes `policy` on `case`.

    `review` is a ReviewOutput, a dict of the same shape, or a path to its JSON.
    `case` is a Case from `load_case`, or a bundled case name.

    `policy="release"` passes only PILOT_ELIGIBLE; with `allow_human_review=True` it
    fails only on REJECT. `policy="regression"` applies the demo thresholds that
    `contract-eval evaluate` gates on. Returns the result for further assertions.
    """
    result = evaluate_review(review, case, alias_mode=alias_mode)
    if _ACTIVE:
        current = os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" ", 1)[0]
        _ACTIVE[-1].stash.setdefault(_RESULTS, []).append((current, result))
    failures = result.failures(policy, allow_human_review=allow_human_review)
    if failures:
        pytest.fail(_explain(result, policy, failures), pytrace=False)
    return result


def _summary(result: ReviewResult) -> str:
    s = result.scores
    return (
        f"clause F1 {s['clause_f1']:.2f} · risk F1 {s['risk_f1']:.2f} · "
        f"severity {s['risk_severity_accuracy']:.2f} · grounding {s['citation_grounding']:.2f} "
        f"({s['citation_grounded']}/{s['citation_total']}) · hallucinations {s['hallucination_count']}"
    )


def _explain(result: ReviewResult, policy: str, failures: list[str]) -> str:
    if policy == "regression":
        heading = f"{result.case.name} review fails {REGRESSION_POLICY_ID}"
        lines = [f"  {failure}" for failure in failures]
    else:
        heading = f"{result.case.name} review is {result.verdict} under {POLICY_ID}"
        lines = []
        if result.blockers:
            lines.append(f"  blockers: {', '.join(result.blockers)}")
        if result.review_items:
            lines.append(f"  review items: {', '.join(result.review_items)}")
    lines.append(f"  {_summary(result)}")
    if result.comparison_only:
        lines.append("  comparison-only: your own contract and answer set, not certifiable")
    return "\n".join([f"contract-eval: {heading}", *lines])


@pytest.fixture
def contract_case():
    """`load_case`: a bundled case by name, or `contract_case(contract=..., gold=...)`."""
    return load_case


def pytest_configure(config: pytest.Config) -> None:
    _ACTIVE.append(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    if config in _ACTIVE:
        _ACTIVE.remove(config)


def pytest_terminal_summary(terminalreporter, exitstatus, config: pytest.Config) -> None:
    results = config.stash.get(_RESULTS, [])
    if not results:
        return
    terminalreporter.section("contract-eval")
    for nodeid, result in results:
        terminalreporter.write_line(f"{result.verdict} {result.case.name}: {_summary(result)}  [{nodeid}]")
