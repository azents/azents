import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, projectApiError } from "./api-error.ts";

void test("projects stable automatic-project error detail", () => {
  assert.deepEqual(
    projectApiError(
      new ApiError(409, {
        detail: {
          code: "automatic_session_projects_revision_conflict",
          message: "Reload the latest policy.",
        },
      }),
    ),
    {
      code: "automatic_session_projects_revision_conflict",
      message: "Reload the latest policy.",
      path: null,
    },
  );
});

void test("maps bounded invalid-path detail without exposing unrelated fields", () => {
  assert.deepEqual(
    projectApiError(
      new ApiError(400, {
        detail: {
          message: "The directory is unavailable.",
          path: "/workspace/agent/missing",
          internal_context: "must not escape",
        },
      }),
    ),
    {
      code: "automatic_session_projects_invalid_path",
      message: "The directory is unavailable.",
      path: "/workspace/agent/missing",
    },
  );
});

void test("does not project non-API errors", () => {
  assert.equal(projectApiError(new Error("Network failed.")), null);
});

void test("validation arrays project only validated messages and preserve bodies", () => {
  const invalid = [
    null,
    0,
    false,
    "raw",
    {},
    { message: 123 },
    { message: {} },
  ];
  for (const body of [invalid, { detail: invalid }]) {
    const error = new ApiError(422, body);
    assert.equal(error.message, "Invalid input.");
    assert.equal(error.status, 422);
    assert.equal(error.body, body);
  }
  assert.equal(
    new ApiError(422, [
      ...invalid,
      { message: "First", opaque: true },
      { message: "" },
      { message: "Second" },
    ]).message,
    "First, Second",
  );
  assert.equal(
    new ApiError(422, {
      detail: [null, { msg: "Required", loc: ["field"] }, { msg: false }],
    }).message,
    "Required",
  );
  assert.equal(
    new ApiError(409, { detail: { extra: "opaque" } }).message,
    '{"extra":"opaque"}',
  );
});
