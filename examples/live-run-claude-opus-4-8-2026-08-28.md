# Live model run, 2026-08-28 (superseded and partly retracted)

**This record contained an invalid comparison. Read
[the 2026-09-01 controlled re-scoring](live-run-claude-opus-5-2026-09-01.md) instead.**

## What was wrong

The original table presented a "before" and "after" column and stated that nothing
about the model changed between them. That was not true. The two columns came from
two separate non-deterministic generations, not from one output scored twice. The
comparison therefore mixed a scorer change with a model-output change and could not
isolate either.

The raw adapter output from this date was not preserved, so those figures cannot be
recomputed. They are withdrawn rather than restated.

## What survives

One observation from this date holds, and was reproduced on 2026-09-01 under a
stricter grounding rule: the model produced no fabricated citations on any of the
three agreements.

The underlying defect the run pointed at was real. Clause-type labels were compared
by string equality, so a review naming the same clause differently scored as having
missed it. That defect is characterised properly, with a controlled experiment and
preserved raw output, in the 2026-09-01 record.

## What changed as a result

Raw adapter output is now preserved and hashed under `examples/raw-output/`, and every
scored run emits `run-provenance.json` recording the output generation time separately
from the scoring time, the scorer version, and digests of the gold sets and source
contracts. A re-scoring can no longer be presented as a model comparison.
