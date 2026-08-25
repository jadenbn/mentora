"""Closed vocabularies shared across the learning engine."""

from __future__ import annotations

from enum import Enum


class SkillOrigin(str, Enum):
    SEED = "seed"
    GENERATED = "generated"
