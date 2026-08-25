/**
 * The network boundary.
 *
 * Two responsibilities: build the multipart request the backend expects, and
 * turn every documented failure into something a student can read.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { analyzeCanvas, apiBaseUrl, TutorApiError } from "@/lib/api/api";
import type { ProblemContext } from "@/types/domain";

const IMAGE = new Blob(["png"], { type: "image/png" });

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const spy = vi.fn(async (_url: string, _init: RequestInit) => response as Response);
  vi.stubGlobal("fetch", spy);
  return spy;
}

const ok = (body: unknown = { interaction_id: "i1", status: "partial", canvas_actions: [], summary: null }) => ({
  ok: true,
  status: 200,
  json: async () => body,
});

const failure = (status: number, detail?: unknown) => ({
  ok: false,
  status,
  json: async () => ({ detail }),
});

const call = (over = {}) =>
  analyzeCanvas({ courseId: "course_demo", mode: "hint", canvasImage: IMAGE, priorAnnotations: [], ...over });

const bodyOf = (spy: ReturnType<typeof mockFetch>) => spy.mock.calls[0][1].body as FormData;

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => vi.unstubAllGlobals());

describe("request construction", () => {
  it("posts to the analyze endpoint", async () => {
    const spy = mockFetch(ok());
    await call();
    expect(spy.mock.calls[0][0]).toContain("/api/tutor/analyze");
    expect(spy.mock.calls[0][1].method).toBe("POST");
  });

  it("posts to the backend, never same-origin", async () => {
    // A same-origin fallback posts to the Next dev server and 404s at :3000,
    // which looks like a missing route rather than a missing env var.
    const spy = mockFetch(ok());
    await call();
    expect(spy.mock.calls[0][0]).toMatch(/^https?:\/\//);
  });

  it("targets the host the page came from, not a hardcoded localhost", async () => {
    // A tablet on the network serves the page from the dev machine's address;
    // "localhost" there would mean the tablet itself.
    const spy = mockFetch(ok());
    await call();
    expect(spy.mock.calls[0][0]).toContain(window.location.hostname);
  });

  it("prefers an explicit NEXT_PUBLIC_API_BASE_URL when one is set", async () => {
    expect(typeof apiBaseUrl()).toBe("string");
    expect(apiBaseUrl()).toMatch(/^https?:\/\/[^/]+$/);
  });

  it("sends the course, the mode, and the image", async () => {
    const spy = mockFetch(ok());
    await call({ mode: "stuck" });
    const body = bodyOf(spy);
    expect(body.get("course_id")).toBe("course_demo");
    expect(body.get("mode")).toBe("stuck");
    expect(body.get("canvas_image")).toBeInstanceOf(Blob);
  });

  it("sends prior annotations as JSON", async () => {
    const spy = mockFetch(ok());
    const prior = [{ x: 0.1, y: 0.2, width: 0.3, height: 0.4 }];
    await call({ priorAnnotations: prior });
    expect(JSON.parse(bodyOf(spy).get("prior_annotations") as string)).toEqual(prior);
  });

  it("sends an empty annotation list on a first interaction", async () => {
    const spy = mockFetch(ok());
    await call();
    expect(JSON.parse(bodyOf(spy).get("prior_annotations") as string)).toEqual([]);
  });

  it("sends the exact structured problem context when present", async () => {
    const spy = mockFetch(ok());
    const problem: ProblemContext = {
      id: "problem_1",
      course_id: "course_demo",
      document_id: "doc_1",
      source: "generated",
      prompt: "Solve $x=1$.",
    };
    await call({ problem });
    expect(JSON.parse(bodyOf(spy).get("problem_context") as string)).toEqual(problem);
  });

  it("lets the browser set the multipart boundary", async () => {
    // Setting Content-Type by hand omits the boundary and the server cannot
    // parse the body. The absence of this header is the point.
    const spy = mockFetch(ok());
    await call();
    expect(spy.mock.calls[0][1].headers).toBeUndefined();
  });

  it("forwards an abort signal so a slow request can be cancelled", async () => {
    const spy = mockFetch(ok());
    const signal = new AbortController().signal;
    await call({ signal });
    expect(spy.mock.calls[0][1].signal).toBe(signal);
  });
});

describe("successful responses", () => {
  it("returns the parsed tutor response", async () => {
    mockFetch(ok({ interaction_id: "i9", status: "correct", canvas_actions: [], summary: "Nice." }));
    await expect(call()).resolves.toMatchObject({ interaction_id: "i9", status: "correct" });
  });
});

describe("failure mapping", () => {
  it.each([
    [413, /too large/i],
    [415, /not supported|format/i],
    [422, /invalid|rejected/i],
    [502, /unavailable/i],
    [504, /too long|timed out/i],
  ])("turns %i into a readable message", async (status, expected) => {
    mockFetch(failure(status));
    await expect(call()).rejects.toThrow(expected);
  });

  it("names what the server is missing when it is unconfigured", async () => {
    mockFetch(failure(503, { missing_settings: ["GEMINI_API_KEY"] }));
    await expect(call()).rejects.toThrow(/GEMINI_API_KEY/);
  });

  it("still explains a 503 with no detail body", async () => {
    mockFetch(failure(503));
    await expect(call()).rejects.toThrow(/not configured/i);
  });

  it("raises a typed error carrying the status", async () => {
    mockFetch(failure(502));
    await expect(call()).rejects.toBeInstanceOf(TutorApiError);
    await call().catch((error: TutorApiError) => expect(error.status).toBe(502));
  });

  it("survives an error body that is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, _init: RequestInit) => ({
        ok: false,
        status: 500,
        json: async () => { throw new SyntaxError("not json"); },
      }) as unknown as Response),
    );
    await expect(call()).rejects.toBeInstanceOf(TutorApiError);
  });

  it("does not translate an unrecognised status into a misleading message", async () => {
    mockFetch(failure(418));
    await expect(call()).rejects.toThrow(/418/);
  });
});
