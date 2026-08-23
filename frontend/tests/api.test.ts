import { beforeEach, describe, expect, it, vi } from "vitest";
import { TutorApiError, analyzeCanvas } from "@/lib/api/api";
import type { TutorRequest } from "@/types/tutor";

const REQUEST = {
  schema_version: "1.0",
  request_id: "ea0e25c0-91c9-4fe4-a990-e82686828b35",
  user_id: "u",
  course_id: "c",
  session_id: "s",
  problem_id: "p",
  mode: "hint",
  problem: { prompt_text: "Differentiate x^2." },
  canvas: { image_width: 100, image_height: 80, shapes: [] },
} as TutorRequest;

const OK_BODY = { schema_version: "1.0", status: "partial", canvas_actions: [] };

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fn = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => response as Response,
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function ok(body: unknown = OK_BODY) {
  return mockFetch({ ok: true, status: 200, json: async () => body });
}

function fail(status: number, detail?: unknown) {
  return mockFetch({
    ok: false,
    status,
    json: async () => ({ detail }),
  });
}

async function call(extra: Parameters<typeof analyzeCanvas>[0] | null = null) {
  return analyzeCanvas(
    extra ?? {
      request: REQUEST,
      canvasImage: new Blob(["png"], { type: "image/png" }),
    },
  );
}

beforeEach(() => vi.unstubAllGlobals());

describe("analyzeCanvas request shape", () => {
  it("posts to the tutor analyze route", async () => {
    const fetchMock = ok();
    await call();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/tutor/analyze");
  });

  it("uses POST with a FormData body", async () => {
    const fetchMock = ok();
    await call();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("sends the request as one JSON string named payload", async () => {
    const fetchMock = ok();
    await call();
    const body = fetchMock.mock.calls[0][1]!.body as FormData;
    expect(JSON.parse(body.get("payload") as string)).toEqual(REQUEST);
  });

  it("attaches the canvas image as a file part", async () => {
    const fetchMock = ok();
    await call();
    const body = fetchMock.mock.calls[0][1]!.body as FormData;
    expect(body.get("canvas_image")).toBeInstanceOf(Blob);
  });

  it("omits selection_image when there is no selection", async () => {
    const fetchMock = ok();
    await call();
    const body = fetchMock.mock.calls[0][1]!.body as FormData;
    expect(body.get("selection_image")).toBeNull();
  });

  it("includes selection_image when a crop is supplied", async () => {
    const fetchMock = ok();
    await call({
      request: REQUEST,
      canvasImage: new Blob(["a"]),
      selectionImage: new Blob(["b"]),
    });
    const body = fetchMock.mock.calls[0][1]!.body as FormData;
    expect(body.get("selection_image")).toBeInstanceOf(Blob);
  });

  it("leaves Content-Type unset so the browser writes the multipart boundary", async () => {
    const fetchMock = ok();
    await call();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toBeUndefined();
  });

  it("forwards an abort signal", async () => {
    const fetchMock = ok();
    const controller = new AbortController();
    await call({
      request: REQUEST,
      canvasImage: new Blob(["a"]),
      signal: controller.signal,
    });
    expect(fetchMock.mock.calls[0][1]!.signal).toBe(controller.signal);
  });

  it("returns the parsed response body", async () => {
    ok(OK_BODY);
    expect(await call()).toEqual(OK_BODY);
  });
});

describe("analyzeCanvas error mapping", () => {
  it("names the missing settings on a 503", async () => {
    fail(503, { missing_settings: ["GEMINI_API_KEY", "PINECONE_API_KEY"] });
    await expect(call()).rejects.toThrow(/GEMINI_API_KEY, PINECONE_API_KEY/);
  });

  it("falls back to a generic message when a 503 names nothing", async () => {
    fail(503, {});
    await expect(call()).rejects.toThrow(/not configured/i);
  });

  it.each([
    [413, /too large/i],
    [415, /not supported/i],
    [422, /invalid/i],
    [502, /unavailable/i],
    [504, /too long/i],
  ])("maps %i onto a readable message", async (status, pattern) => {
    fail(status);
    await expect(call()).rejects.toThrow(pattern);
  });

  it("includes the status code for an unmapped failure", async () => {
    fail(418);
    await expect(call()).rejects.toThrow(/418/);
  });

  it("throws a TutorApiError carrying the status and detail", async () => {
    fail(503, { missing_settings: ["GEMINI_API_KEY"] });
    const error = await call().catch((e) => e);
    expect(error).toBeInstanceOf(TutorApiError);
    expect(error.status).toBe(503);
    expect(error.detail).toEqual({ missing_settings: ["GEMINI_API_KEY"] });
  });

  it("still throws when the error body is not JSON", async () => {
    mockFetch({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError("not json");
      },
    });
    await expect(call()).rejects.toBeInstanceOf(TutorApiError);
  });
});
