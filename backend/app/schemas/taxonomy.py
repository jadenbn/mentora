"""Provider output for skill-taxonomy generation, before build_taxonomy runs.

Shape-only validation lives here. The rules that make a taxonomy actually
usable — resolved prereqs against the full course graph, no cycles, bounded
skill count — are enforced once, in app.services.taxonomy.build_taxonomy, the
same path a hand-authored course JSON takes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawSkillEntry(StrictModel):
    """One skill as the provider emits it — pre-normalization, pre-origin."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    difficulty_band: float = Field(ge=0.0, le=1.0)
    prereqs: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    question_forms: list[str] = Field(default_factory=list, max_length=12)


class TaxonomyPlan(StrictModel):
    """A batch of skills proposed from course material.

    Used for both full-course generation (many skills, no existing_skill_ids)
    and emergent single-skill proposals (one entry, existing_skill_ids set).
    """

    skills: list[RawSkillEntry] = Field(min_length=1, max_length=40)
