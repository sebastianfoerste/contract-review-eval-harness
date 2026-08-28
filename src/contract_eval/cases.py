"""The evaluated contract types.

Adding a case means adding four files and one entry here:

    data/<case>_sample.md      the synthetic contract
    expected/<case>.json       the human-authored gold answer
    fixtures/<case>_stub.json  the deterministic offline adapter output
    robustness/campaign.v1.json  scenarios naming the case (optional)

Every consumer derives its case list from ALL_CASES, so nothing else hardcodes
the set.
"""

from __future__ import annotations

ALL_CASES: tuple[str, ...] = ("nda", "saas", "dpa")
