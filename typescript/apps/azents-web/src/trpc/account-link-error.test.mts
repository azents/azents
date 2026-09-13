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

void test("projects a structured provider availability failure", () => {
  const error = new ApiError(409, {
    detail: {
      code: "provider_unavailable",
      message: "Slack account connection is unavailable",
    },
  });

  assert.equal(accountLinkFailureReason(error), "provider_unavailable");
});

void test("projects a configuration change as a restartable callback failure", () => {
  const error = new ApiError(409, {
    detail: {
      code: "configuration_changed",
      message: "Provider configuration changed.",
    },
  });

  assert.equal(accountLinkFailureReason(error), "configuration_changed");
});

void test("does not treat unrelated forbidden responses as elevation", () => {
  const error = new ApiError(403, {
    detail: "Forbidden",
  });

  assert.equal(accountLinkFailureReason(error), null);
});
