"""Closed vocabularies shared between grading, attempts, and skill state."""

from __future__ import annotations

from enum import Enum


class MisconceptionTag(str, Enum):
    DROPPED_TERM = "dropped-term"
    SIGN_ERROR = "sign-error"
    WRONG_RULE_SELECTED = "wrong-rule-selected"
    INCOMPLETE_SIMPLIFICATION = "incomplete-simplification"
    ARITHMETIC_SLIP = "arithmetic-slip"
    NOTATION_ERROR = "notation-error"
    NO_ATTEMPT = "no-attempt"


class SkillOrigin(str, Enum):
    SEED = "seed"
    GENERATED = "generated"
