"""Provider failures, in the two shapes the API needs to tell apart.

Separate from the adapter so the API layer can import them without pulling in
a provider SDK.
"""

from __future__ import annotations


class TutorWorkflowError(RuntimeError):
    """The tutor could not produce a usable plan.

    Carries no provider text: upstream messages can quote credentials and
    prompt fragments, and this reaches an HTTP boundary.
    """


class TutorWorkflowTimeout(TutorWorkflowError):
    """The provider did not answer in time."""
