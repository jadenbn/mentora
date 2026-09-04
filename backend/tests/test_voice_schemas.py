"""The voice contract.

One helper carries the whole normalization decision, and two callers depend on
it meaning the same thing: the transcribe route, which turns None into "no
speech", and the tutor route, which turns None into a rejected request.
"""

from __future__ import annotations

import pytest

from app.schemas.voice import MAX_TRANSCRIPT_CHARS, TranscriptionResponse, normalize_transcript


class TestNormalization:
    def test_a_spoken_question_survives_intact(self):
        assert normalize_transcript("why can't I do this?") == "why can't I do this?"

    def test_surrounding_and_repeated_whitespace_collapses(self):
        assert normalize_transcript("  why   is\n this  wrong? ") == "why is this wrong?"

    @pytest.mark.parametrize("silence", ["", "   ", "\n\t ", "\r\n"])
    def test_a_recording_with_no_words_in_it_becomes_none(self, silence):
        assert normalize_transcript(silence) is None

    def test_length_is_left_to_the_caller(self):
        # Refusing an over-long client transcript and shortening an over-long
        # provider one are different decisions; neither belongs here.
        assert normalize_transcript("a" * 5_000) == "a" * 5_000


class TestResponse:
    def test_an_empty_transcript_is_not_a_valid_response(self):
        with pytest.raises(ValueError):
            TranscriptionResponse(transcript="")

    def test_a_transcript_past_the_cap_is_not_a_valid_response(self):
        with pytest.raises(ValueError):
            TranscriptionResponse(transcript="a" * (MAX_TRANSCRIPT_CHARS + 1))

    def test_unknown_fields_are_rejected(self):
        with pytest.raises(ValueError):
            TranscriptionResponse(transcript="hello", confidence=0.9)
