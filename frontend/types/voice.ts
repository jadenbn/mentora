/**
 * Mirror of the backend voice contract.
 *
 * Source of truth: backend/app/schemas/voice.py. Voice is an input to the
 * canvas tutor, so the only thing that crosses this boundary is one spoken
 * instruction — the audio never leaves the request that carried it.
 */

export interface TranscriptionResponse {
  transcript: string;
}

/**
 * The cap the tutor endpoint enforces, mirrored so an edited transcript is
 * refused here rather than coming back as a 422.
 *
 * Source of truth: MAX_TRANSCRIPT_CHARS in backend/app/schemas/voice.py.
 * Transcription already truncates provider output to this length; the student
 * can only exceed it by typing, which is why the confirmation step re-checks.
 */
export const MAX_TRANSCRIPT_CHARS = 1_000;
