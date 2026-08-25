"""Read and write which skills a generated problem exercises.

Two functions on one table, kept apart from both the question service that
writes them and the ingestion path that reads them, because the pair is the
attribution invariant: whatever generation recorded here is what an attempt
on that problem moves. A client's claim is only ever cross-checked against it.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, delete, select

from app.models.problem_skill import ProblemSkill
from app.models.skill import Skill

logger = logging.getLogger(__name__)


def set_problem_skills(session: Session, problem_id: str, skill_ids: list[str]) -> None:
    """Record which skills a problem targets, preserving declared order.

    Replaces any existing rows. Ids not in the taxonomy are dropped with a
    warning rather than raising: attribution is bookkeeping on the generation
    path, and a skill that vanished between selection and here must not cost
    the student the problem. The foreign key on skill_id stays as the backstop
    for anything that writes around this function.
    """
    ordered = list(dict.fromkeys(skill_ids))
    known = set(
        session.exec(select(Skill.id).where(Skill.id.in_(ordered))).all()
    ) if ordered else set()

    unknown = [s for s in ordered if s not in known]
    if unknown:
        logger.warning(
            "problem %s: dropping attribution to unknown skill(s) %s",
            problem_id,
            unknown,
        )

    session.exec(delete(ProblemSkill).where(ProblemSkill.problem_id == problem_id))
    for ordinal, skill_id in enumerate(s for s in ordered if s in known):
        session.add(
            ProblemSkill(problem_id=problem_id, skill_id=skill_id, ordinal=ordinal)
        )
    session.commit()


def get_problem_skills(session: Session, problem_id: str) -> list[str]:
    """Skills a problem targets, in declared order. Empty if none recorded."""
    rows = session.exec(
        select(ProblemSkill)
        .where(ProblemSkill.problem_id == problem_id)
        .order_by(ProblemSkill.ordinal)
    ).all()
    return [row.skill_id for row in rows]
