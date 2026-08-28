"""The learning engine: what to ask a student next, and how hard to make it.

Everything in this package is one subsystem with one owner. It has no
student-facing surface of its own -- selection happens inside question
generation, and per-topic accuracy is shown only on the dev dashboard -- so
the names re-exported here are the whole of what the rest of the backend is
meant to touch.

Import from `app.engine`, not from the modules inside it. Anything reaching
past this file (`from app.engine.selection import _staleness`) is either a
bug or a sign this surface needs to grow on purpose.

Consumers, in full:

* app.api.questions   -- picks a topic and a difficulty at generation time
* app.services.tutor_service, app.agents.tutor_workflow -- LearnerContext
* app.bootstrap       -- mounts the two routers

Two modules the engine cares about deliberately live outside it:
`services.taxonomy` and `services.attribution` are the bridge between
question generation and this package -- generation writes them, the engine
reads them -- so they stay on the generation side until the taxonomy moves
to the database.
"""

from app.engine.accuracy import (
    PRIOR_ACCURACY,
    difficulty_bucket,
    estimated_accuracy,
    observed_accuracy,
    push_outcome,
    score_attempt,
)
from app.engine.hints import hints_taken, record_hint
from app.engine.profile import (
    LearnerContext,
    StudentProfile,
    get_learner_context,
    get_profile,
)
from app.engine.selection import TopicPick, mark_served, pick_topic
from app.engine.simulation import SimulationReport, simulate
from app.engine.student_model_service import (
    UnknownSkillError,
    get_skills_overview,
    record_attempt,
)

__all__ = [
    # scoring and estimation (pure)
    "PRIOR_ACCURACY",
    "difficulty_bucket",
    "estimated_accuracy",
    "observed_accuracy",
    "push_outcome",
    "score_attempt",
    # what to serve next
    "TopicPick",
    "mark_served",
    "pick_topic",
    # who the student is
    "LearnerContext",
    "StudentProfile",
    "get_learner_context",
    "get_profile",
    # recording what happened
    "UnknownSkillError",
    "get_skills_overview",
    "record_attempt",
    "hints_taken",
    "record_hint",
    # measuring the policy
    "SimulationReport",
    "simulate",
]
