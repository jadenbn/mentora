"""Provider output for skill-taxonomy generation, before build_taxonomy runs.

Shape-only validation lives here. The rules that make a taxonomy actually
usable — resolved prereqs against the full course graph, no cycles, bounded
skill count — are enforced once, in app.services.taxonomy.build_taxonomy, the
same path a hand-authored course JSON takes.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Mirrors app.services.taxonomy._MAX_ENTRY_CHARS. Duplicated rather than
# imported: agents/ (which builds this schema) does not depend on services/
# (see agents/taxonomy_workflow.py's module docstring) — the same trade-off
# already made for that module's own cycle-detection DFS. Catching this here
# means a violation gets the workflow's own repair retry, with the real
# error fed back, instead of surfacing as a hard failure downstream in
# build_taxonomy with no chance to fix it.
_MAX_ENTRY_CHARS = 80

_ShortEntry = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_CHARS)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawSkillEntry(StrictModel):
    """One skill as the provider emits it — pre-normalization, pre-origin."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    difficulty_band: float = Field(ge=0.0, le=1.0)
    prereqs: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[_ShortEntry] = Field(default_factory=list, max_length=12)
    question_forms: list[_ShortEntry] = Field(default_factory=list, max_length=12)


class TaxonomyPlan(StrictModel):
    """A batch of skills proposed from course material.

    Used for both full-course generation (many skills, no existing_skill_ids)
    and emergent single-skill proposals (one entry, existing_skill_ids set).
    """

    skills: list[RawSkillEntry] = Field(min_length=1, max_length=40)


#: The provider-side JSON schema for one RawSkillEntry. Kept beside the model
#: it describes so the two cannot drift.
SKILL_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "difficulty_band": {"type": "number", "minimum": 0, "maximum": 1},
        "prereqs": {"type": "array", "items": {"type": "string"}},
        "keywords": {
            "type": "array",
            "items": {"type": "string", "maxLength": _MAX_ENTRY_CHARS},
        },
        "question_forms": {
            "type": "array",
            "items": {"type": "string", "maxLength": _MAX_ENTRY_CHARS},
        },
    },
    "required": ["id", "name", "description", "difficulty_band"],
}
