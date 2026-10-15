# Gate your CI on contract-eval

Three ways to fail a build when a contract review regresses, from least to most code.

## 1. The GitHub Action

The repository root is a composite action. It installs `contract-eval` from the action's
own checkout (no PyPI needed), runs [`contract-eval score`](score-your-own-tool.md) on
every review file you name, writes a summary table and each scorecard to the job
summary, and fails the step on `REJECT`.

```yaml
- name: Score the reviews
  uses: sebastianfoerste/contract-review-eval-harness@main   # pin a tag or SHA once released
  with:
    reviews: reviews/*.json
    case: nda
```

A complete workflow to copy is in
[`examples/ci/contract-eval.yml`](../examples/ci/contract-eval.yml).

| Input | Default | Meaning |
|---|---|---|
| `reviews` | required | review JSON files: whitespace-separated paths or globs, `**` recurses |
| `case` | | bundled case: `nda`, `saas` or `dpa` |
| `contract`, `gold` | | your own contract and answer set, instead of `case` |
| `aliases` | `on` | apply the answer set's declared clause synonyms |
| `fail-on` | `reject` | `human-review` also fails on `HUMAN_REVIEW_REQUIRED` |
| `out` | `contract-eval-results` | per review: `<path>.md` scorecard and `<path>.json` sealed result |
| `python-version` | `3.12` | Python that runs the harness, 3.11 or later |

| Output | Meaning |
|---|---|
| `decision` | worst decision across the reviews: `REJECT`, `HUMAN_REVIEW_REQUIRED` or `PILOT_ELIGIBLE` |
| `results-dir` | the `out` directory, for `actions/upload-artifact` |

The step exits 1 when a decision fails the gate and 2 when a review or answer set
cannot be read; each failing file gets an error annotation naming the blockers and
review items. A result scored against your own answer set is labelled *comparison
only, not certifiable*, exactly as on the command line.

The action runs on Linux and macOS runners. Inputs reach the scorer as environment
variables, so a file name is never executed as shell code. This repository's CI runs
the action against the deliberately flawed NDA stub and requires it to fail.

## 2. The command line

Any CI system can call the command directly and use its exit status:

```bash
uvx --from git+https://github.com/sebastianfoerste/contract-review-eval-harness \
  contract-eval score reviews/nda.json --case nda --out results
```

Append the printed scorecard to `$GITHUB_STEP_SUMMARY`, or keep `results/` as an
artifact.

## 3. pytest

Installing the package registers a pytest plugin, so a reviewer's own test suite can
assert on a review:

```python
from contract_eval.pytest_plugin import assert_review_passes

def test_nda_review_is_releasable(contract_case):
    assert_review_passes("reviews/nda.json", contract_case("nda"))
```

[`examples/test_my_reviewer.py`](../examples/test_my_reviewer.py) is a complete
example, including a softer gate that fails only on `REJECT`.

## What passing means

`PILOT_ELIGIBLE` means every requirement of the release policy is met on that
contract. It supports a supervised pilot at most and never authorizes reliance on a
review: every flagged risk and every citation still needs a qualified lawyer.
