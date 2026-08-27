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
