"""Closed vocabularies shared between grading, attempts, and skill state."""

from __future__ import annotations

from enum import Enum


class MisconceptionTag(str, Enum):
    """Subject-agnostic: these must mean the same thing in any course, since
    a single closed vocabulary is shared across every taxonomy."""

    CONCEPTUAL_ERROR = "conceptual-error"  # wrong idea/method chosen
    PROCEDURAL_ERROR = "procedural-error"  # right idea, executed incorrectly
    CARELESS_ERROR = "careless-error"      # right idea and method, slipped
    INCOMPLETE = "incomplete"              # correct so far, not finished
    NO_ATTEMPT = "no-attempt"


class SkillOrigin(str, Enum):
    SEED = "seed"
    GENERATED = "generated"
