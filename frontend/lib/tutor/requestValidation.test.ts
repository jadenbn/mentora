import assert from "node:assert/strict";
import test from "node:test";

import { messageForStatus } from "../api/errors.ts";
import {
  TutorRequestValidationError,
  validateTutorRequest,
} from "./requestValidation.ts";
import type { TutorRequest } from "../../types/tutor.ts";

function requestWithDimensions(width: number, height: number): TutorRequest {
  return {
    schema_version: "1.0",
    request_id: "ea0e25c0-91c9-4fe4-a990-e82686828b35",
    user_id: "user",
    course_id: "calc1",
    session_id: "session",
    problem_id: "problem",
    mode: "hint",
    problem: { prompt_text: "Differentiate x squared." },
    canvas: { image_width: width, image_height: height, shapes: [] },
  };
}

test("fractional image dimensions are rejected before transport", () => {
  assert.throws(
    () => validateTutorRequest(requestWithDimensions(639.75, 480)),
    (error) =>
      error instanceof TutorRequestValidationError &&
      error.detail.field === "canvas.image_width",
  );
});

test("422 errors expose only a safe field path", () => {
  const detail = [
    {
      loc: ["canvas", "image_width"],
      msg: "Input should be a valid integer, got private content",
    },
  ];

  assert.equal(
    messageForStatus(422, detail),
    "The tutor request has an invalid canvas.image_width. Please refresh the canvas and try again.",
  );
  assert.doesNotMatch(messageForStatus(422, detail), /private content/);
});
