"""Who wrote which annotation, by role.

Slot and label are separate. The role slot is stable plumbing: directory and file
names key off it, so replacing or adding a reviewer never renames artifacts or breaks
the comparison script. The label is what `annotator_id` records, so a reader of any
gold set can see which role's judgment it carries.

Annotators are recorded by role label, not by personal name. A public repository is a
permanent, searchable record, so no annotator's name belongs in it.
"""

from __future__ import annotations

from typing import NamedTuple


class Annotator(NamedTuple):
    slot: str
    name: str
    role: str


FIRST = Annotator(
    slot="annotator-a",
    name="Annotator A",
    role="Author of the original v1 gold sets and the candidate v2 obligations.",
)

SECOND = Annotator(
    slot="annotator-b",
    name="Annotator B",
    role="Independent second annotator, working blind from the annotation pack.",
)

BY_SLOT = {annotator.slot: annotator for annotator in (FIRST, SECOND)}
