"""Which skill(s) a generated problem exercises.

This is the table the whole server-side attribution guarantee rests on: when
an attempt comes back, these rows -- not the client's claim -- decide which
skills move. It lives in the SQLModel layer, beside Skill, specifically so
that skill_id can carry a real foreign key. While it sat in the raw-sqlite3
repository the two schemas could not reference each other, so a problem could
be attributed to a skill id that did not exist and nothing would notice.

ON DELETE CASCADE: re-seeding a course deletes and reinserts its seed skills,
so a skill that a hand edit renamed or removed takes its attributions with it.
The historical record is unaffected -- Attempt stores the resolved skill list
of its own, and that ledger is immutable.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class ProblemSkill(SQLModel, table=True):
    problem_id: str = Field(primary_key=True, index=True)
    skill_id: str = Field(
        primary_key=True,
        foreign_key="skill.id",
        ondelete="CASCADE",
    )
    #: Declared order. The first skill is the problem's primary one, which is
    #: what selection's recency penalty looks at.
    ordinal: int = Field(default=0)
