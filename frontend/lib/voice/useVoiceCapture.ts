"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { createVoiceCapture, type VoiceState } from "@/lib/voice/voiceCapture";

const SERVER_STATE: VoiceState = { phase: { status: "idle" }, error: null };

export interface VoiceControls {
  start: () => void;
  stop: () => void;
  cancel: () => void;
  edit: (transcript: string) => void;
  ask: () => void;
  rerecord: () => void;
}

/**
 * React binding for the recording lifecycle.
 *
 * Deliberately thin: the machine in voiceCapture.ts owns every transition and
 * every teardown, so all this adds is subscription and a teardown on unmount.
 * It is built once and never rebuilt — rebuilding mid-recording would strand a
 * live microphone — so a changed `submit` is pushed into it instead.
 *
 * `mount` is paired setup/teardown rather than a one-way disposal, so Strict
 * Mode's effect replay re-arms the retained machine instead of retiring it for
 * the life of the page.
 */
export function useVoiceCapture(options: {
  submit: (transcript: string) => Promise<void>;
}): VoiceState & VoiceControls {
  const [capture] = useState(() => createVoiceCapture({ submit: options.submit }));

  useEffect(() => {
    capture.setSubmit(options.submit);
  }, [capture, options.submit]);

  useEffect(() => capture.mount(), [capture]);

  const state = useSyncExternalStore(
    capture.subscribe,
    capture.getState,
    () => SERVER_STATE,
  );

  return {
    ...state,
    start: useCallback(() => capture.start(), [capture]),
    stop: useCallback(() => capture.stop(), [capture]),
    cancel: useCallback(() => capture.cancel(), [capture]),
    edit: useCallback((transcript: string) => capture.edit(transcript), [capture]),
    ask: useCallback(() => capture.ask(), [capture]),
    rerecord: useCallback(() => capture.rerecord(), [capture]),
  };
}
