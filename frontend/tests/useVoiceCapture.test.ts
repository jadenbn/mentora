/**
 * The React binding, under Strict Mode.
 *
 * Next's App Router enables Strict Mode, which mounts, tears down, and mounts
 * again. A cleanup that retired the machine permanently would leave the
 * retained instance dead and the microphone button inert in development, so
 * the setup/teardown pair has to survive being replayed.
 *
 * The browser APIs are stubbed rather than the module's dependencies, so this
 * exercises the real path from the button to `getUserMedia`.
 */

import { createElement, StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVoiceCapture } from "@/lib/voice/useVoiceCapture";

class StubRecorder {
  state: "recording" | "inactive" = "inactive";
  ondataavailable: unknown = null;
  onstop: unknown = null;
  onerror: unknown = null;
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
  }
}

let track: { stop: ReturnType<typeof vi.fn> };
let getUserMedia: ReturnType<typeof vi.fn>;
let container: HTMLDivElement;
let root: Root;

function Harness() {
  const voice = useVoiceCapture({ submit: async () => {} });
  return createElement(
    "button",
    { onClick: voice.start, type: "button" },
    voice.phase.status,
  );
}

const button = () => container.querySelector("button") as HTMLButtonElement;

beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  track = { stop: vi.fn() };
  getUserMedia = vi.fn(async () => ({ getTracks: () => [track] }) as unknown as MediaStream);
  vi.stubGlobal("MediaRecorder", StubRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia },
    configurable: true,
  });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  Reflect.deleteProperty(navigator, "mediaDevices");
  vi.unstubAllGlobals();
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = false;
});

const mount = async () => {
  await act(async () => {
    root.render(createElement(StrictMode, null, createElement(Harness)));
  });
};

describe("under Strict Mode", () => {
  it("still opens the microphone after the effect has been replayed", async () => {
    // The regression: development effect replay used to retire the machine the
    // component kept using, so this click reached a permanently dead guard.
    await mount();

    await act(async () => button().click());

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(button().textContent).toBe("recording");
  });

  it("does not start recording merely by mounting", async () => {
    await mount();
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(button().textContent).toBe("idle");
  });
});

describe("on real unmount", () => {
  it("releases the microphone", async () => {
    await mount();
    await act(async () => button().click());
    expect(track.stop).not.toHaveBeenCalled();

    await act(async () => root.unmount());

    expect(track.stop).toHaveBeenCalled();
  });
});
