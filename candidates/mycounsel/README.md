# My Counsel native candidate track

This is a separate synthetic engineering track. It does not enter `ALL_CASES`,
the three-case reference freeze, or a release certificate. It demonstrates the
actual My Counsel candidate prompt, schema and validators through a replay
gateway. The recorded findings are hand-authored fixtures, including a duplicate
and an unknown playbook reference. No model run, independent annotation or legal
quality improvement is claimed.

## Reproduce

With the private ZuRecht checkout beside this repository:

```sh
python candidates/mycounsel/build_fixtures.py
cd ../zurecht
pnpm exec tsx scripts/record-contract-candidates.ts base commercial /tmp/candidate-run.json
cd ../contract-review-eval-harness
uv run python -m contract_eval.candidates /tmp/candidate-run.json --document candidates/mycounsel/ict-base.docx
uv run pytest tests/test_candidates.py
```

The recorder refuses to overwrite an earlier attempt. Other arguments are
`changed` or `injection` and `dora`. Regenerating a recording intentionally changes
its start time, elapsed time and source-revision metadata. Fixture DOCX generation
is deterministic. The exact original bytes, paragraph anchors, playbook text,
business instructions, prompt version, code revision and dirty-tree state are
retained. Errors and refusals remain attempts. Provider error text is excluded.
The current gateway exposes no usage or cost, so the artifact states that gap.

The CLI is offline only. Before a live campaign, add reservation of the maximum
attempt cost, including retries, against the separate EUR 100 cap; verify the
provider price and run approval; retain every attempt. The current recording
function accepts the normal gateway seam but is not a budget enforcement layer.

## Meaning of the measures

Quotation validity checks exact text under the supplied source anchor. Playbook
validity checks an existing stable ID and matching category. Missing findings
must have no source quote or existing-clause anchor; their insertion anchor, if
any, must exist. Duplicate findings are counted separately. A reference file
must bind to the same document and playbook. Rule/anchor precision and recall
are only a matching proxy, with duplicate and invalid findings in the precision
denominator. Matching cannot establish a correct legal explanation or amendment.

No reference is supplied as independent gold. The optional reference schema
supports a `DRAFT` state and records a reviewer evidence reference; presence of
that string does not verify the reviewer. Blind annotation and adjudication
remain open. Severity accuracy and complete clause coverage are unavailable
because the native My Counsel output does not contain those fields.

## Case and legal review boundary

The fictional customer is a German credit institution. The exercise assumes that
the ICT service supports a critical or important function. These are stipulated
facts, not a perimeter determination. The commercial playbook contains customer
preferences and risk judgments. The six DORA points are a deliberately limited
selection from Article 30; they do not constitute a complete DORA, subcontracting
or outsourcing review. Proposed wording needs lawyer assessment.

The [official published Regulation (EU) 2022/2554](https://eur-lex.europa.eu/eli/reg/2022/2554/oj/eng)
was inspected on 10 October 2026. The source was marked in force and presented
the 27 December 2022 text. Pinpoints for the selected requirements are in
`dora.json`: Article 30(2)(b), (d), (f), and 30(3)(a), (e), (f).
The Article 30(3) requirements depend on the stipulated critical/important
function. Legal source review is distinct from independent benchmark annotation.

The `changed` document repairs only the location-notice clause. The `injection`
document adds hostile reviewer instructions as source evidence. The replay
fixture does not simulate model sensitivity to either change: observed robustness
requires retained live outputs. Public-document editor exercises belong to a
separate pilot corpus and must never be relabelled synthetic benchmark evidence.
