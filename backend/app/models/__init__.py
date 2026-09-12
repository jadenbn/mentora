"""The taxonomy and attribution tables, imported for their side effect.

SQLModel.metadata only knows about a table whose module has been imported, so
init_db() creating the schema -- and ProblemSkill's foreign key resolving to
skill.id -- depends on every model being loaded first. db.py imports this
package and app.engine.models together, which is what makes both halves of
the schema present before create_all runs.

The engine's own tables live in app/engine/models. Nothing here imports them:
the engine depends on the taxonomy, not the other way round, and a back-edge
from this package would make that circular.
"""

from app.models.problem_skill import ProblemSkill
from app.models.skill import Skill

__all__ = [
    "ProblemSkill",
    "Skill",
]
