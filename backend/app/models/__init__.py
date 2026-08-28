"""Every table in the SQLModel layer, imported for its side effect.

SQLModel.metadata only knows about a table whose module has been imported, so
init_db() creating the schema -- and ProblemSkill's foreign key resolving to
skill.id -- depends on every model being loaded first. Importing them here,
and importing this package from db.py, makes that explicit instead of relying
on whichever service happened to be imported along the way.
"""

from app.models.attempt import Attempt
from app.models.course_taxonomy_version import CourseTaxonomyVersion
from app.models.hint_usage import HintUsage
from app.models.problem_skill import ProblemSkill
from app.models.skill import Skill
from app.models.skill_state import SkillState

__all__ = [
    "Attempt",
    "CourseTaxonomyVersion",
    "HintUsage",
    "ProblemSkill",
    "Skill",
    "SkillState",
]
