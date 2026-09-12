"""The engine's tables, imported for their side effect.

SQLModel.metadata only knows about a table whose module has been imported.
app/db.py imports this package alongside app.models so both halves of the
schema are registered before init_db() creates it.

Skill and ProblemSkill are not here: they belong to the taxonomy and the
attribution bridge, which stay on the generation side (see app/engine).
"""

from app.engine.models.attempt import Attempt
from app.engine.models.hint_usage import HintUsage
from app.engine.models.skill_state import SkillState

__all__ = ["Attempt", "HintUsage", "SkillState"]
