import assert from "node:assert/strict";
import test from "node:test";
import { TRPCError } from "@trpc/server";
import { ApiError, mapExpectedError, projectApiError } from "./api-error.ts";

void test("preserves safe deletion conflicts across every mutation router", () => {
  const error = new ApiError(409, {
    detail: {
      code: "agent_decommissioning",
      message: "Agent is being deleted and is read-only.",
      internal_error: "never project diagnostics",
    },
  });
  const mapped = mapExpectedError(error, {});
  assert.ok(mapped instanceof TRPCError);
  assert.equal(mapped.code, "CONFLICT");
  assert.deepEqual(projectApiError(mapped.cause), {
    code: "agent_decommissioning",
    message: "Agent is being deleted and is read-only.",
    path: null,
  });
});

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
