"""Who wrote which annotation.

Identity and role are separate. The role slot is stable plumbing: directory and file
names key off it, so replacing or adding a reviewer never renames artifacts or breaks
the comparison script. The identity is the person, recorded in `annotator_id` so a
reader of any gold set can see whose judgment it carries.

Both annotators are named with their agreement. A public repository is a permanent,
searchable record, so a reviewer is named only once they have said yes.
"""

from __future__ import annotations

from typing import NamedTuple


class Annotator(NamedTuple):
    slot: str
    name: str
    role: str


FIRST = Annotator(
    slot="annotator-a",
    name="Sebastian Förste",
    role="Author of the original v1 gold sets and the candidate v2 obligations.",
)

SECOND = Annotator(
    slot="annotator-b",
    name="Karsten Schmidt",
    role="Independent second annotator, working blind from the annotation pack.",
)

BY_SLOT = {annotator.slot: annotator for annotator in (FIRST, SECOND)}
