import assert from "node:assert/strict";
import test from "node:test";
import { accountLinkFailureReason } from "./account-link-error.ts";
import { ApiError } from "./api-error.ts";

void test("projects the existing plain elevation dependency response", () => {
  const error = new ApiError(403, {
    detail: "Elevated access required",
  });

  assert.equal(accountLinkFailureReason(error), "elevation_required");
});

void test("keeps structured membership failure distinct from elevation", () => {
  const error = new ApiError(403, {
    detail: {
      code: "membership_required",
      message: "Workspace membership is required",
    },
  });

  assert.equal(accountLinkFailureReason(error), "membership_required");
});

void test("does not treat unrelated forbidden responses as elevation", () => {
  const error = new ApiError(403, {
    detail: "Forbidden",
  });

  assert.equal(accountLinkFailureReason(error), null);
});
