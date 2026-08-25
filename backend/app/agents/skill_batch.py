"""Structural checks for one batch of proposed skills, shared by every
adapter that can propose skills inline: taxonomy_workflow.py (a course's
whole taxonomy, or one emergent skill) and question_workflow.py (the
skill(s) a generated question exercises).

The same batch-local rules apply everywhere a model proposes skills: ids
unique within the batch, every prereq resolves to either a batch id or a
caller-supplied existing id, no same-batch cycle. Graph-wide checks against
the full course (a prereq or cycle spanning existing skills this batch
can't see) are app.services.taxonomy.build_taxonomy's job, run downstream by
the caller — this module never touches a database.
"""

from __future__ import annotations

from app.schemas.taxonomy import RawSkillEntry

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
            "items": {"type": "string", "maxLength": 80},
        },
        "question_forms": {
            "type": "array",
            "items": {"type": "string", "maxLength": 80},
        },
    },
    "required": ["id", "name", "description", "difficulty_band"],
}


def find_cycle(entries: list[RawSkillEntry]) -> str | None:
    """DFS over one batch's own prereq edges. Returns a description or None.

    Only edges between ids present in this batch are checked — a prereq
    pointing outside the batch (at an existing course skill) cannot
    participate in a same-batch cycle by construction.
    """
    by_id = {entry.id: entry for entry in entries}
    WHITE, GRAY, BLACK = 0, 1, 2
    state = {entry.id: WHITE for entry in entries}

    def visit(skill_id: str, path: list[str]) -> str | None:
        state[skill_id] = GRAY
        for prereq_id in by_id[skill_id].prereqs:
            if prereq_id not in by_id:
                continue
            if state[prereq_id] == GRAY:
                return " -> ".join(path + [prereq_id])
            if state[prereq_id] == WHITE:
                found = visit(prereq_id, path + [prereq_id])
                if found:
                    return found
        state[skill_id] = BLACK
        return None

    for entry in entries:
        if state[entry.id] == WHITE:
            found = visit(entry.id, [entry.id])
            if found:
                return found
    return None


def validate_skill_batch(entries: list[RawSkillEntry], known_ids: set[str]) -> None:
    """Raise ValueError on any batch-local structural problem in entries."""
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise ValueError(f"duplicate skill id in batch: {entry.id}")
        seen.add(entry.id)

    resolvable = seen | known_ids
    for entry in entries:
        unresolved = [p for p in entry.prereqs if p not in resolvable]
        if unresolved:
            raise ValueError(f"{entry.id}: prereq(s) resolve nowhere: {unresolved}")

    cycle = find_cycle(entries)
    if cycle:
        raise ValueError(f"prerequisite cycle detected: {cycle}")
