"""The voice wire contract.

Voice is an input to the canvas tutor, not a conversation. The only thing that
crosses this boundary is one short spoken instruction, already transcribed —
the audio never leaves the request that carried it and is never persisted.

The transcript is model output, so it is untrusted twice over: once as speech
the tutor did not choose, and once as text a provider generated. It is trimmed
and length-capped before it can reach a prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: A spoken instruction is a sentence or two. The cap bounds what untrusted
#: provider output can push into a prompt; it is not a product limit.
MAX_TRANSCRIPT_CHARS = 1_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptionResponse(StrictModel):
    """One utterance, ready to be handed to the tutor as context."""

    transcript: str = Field(min_length=1, max_length=MAX_TRANSCRIPT_CHARS)


def normalize_transcript(raw: str) -> str | None:
    """Collapse a transcript to what is safe to put in a prompt.

    Returns None when nothing was said. Silence and background noise both come
    back as whitespace, and neither is an instruction worth a model call.
    Truncation is deliberately *not* done here: refusing an over-long client
    transcript and shortening an over-long provider one are different
    decisions, made by their own callers.
    """
    collapsed = " ".join(raw.split())
    return collapsed or None
