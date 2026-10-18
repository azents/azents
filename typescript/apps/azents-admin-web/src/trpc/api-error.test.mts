import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, mapExpectedError } from "./api-error.ts";

void test("API validation errors decode consumed messages without losing status on malformed entries", () => {
  for (const body of [
    [null, 1, {}, { message: false }],
    { detail: [null, 1, {}, { msg: [] }] },
  ]) {
    const error = new ApiError(422, body);
    assert.equal(error.status, 422);
    assert.equal(error.body, body);
    assert.equal(error.message, "The input is invalid.");
    assert.equal(error.name, "ApiError");
  }
  assert.equal(
    new ApiError(400, [
      null,
      { message: "First", extension: null },
      { message: "Second" },
    ]).message,
    "First, Second",
  );
  assert.equal(
    new ApiError(400, { detail: [null, { msg: "Required", loc: ["email"] }] })
      .message,
    "Required",
  );
});
void test("API structured details and expected HTTP mapping preserve their current contracts", () => {
  const detail = {
    code: "profile_in_use",
    message: "In use",
    extensions: { future: null },
  };
  const error = new ApiError(409, { detail });
  assert.equal(error.message, JSON.stringify(detail));
  assert.equal(
    mapExpectedError(error, { 409: "CONFLICT" }) instanceof Error,
    true,
  );
  assert.equal(mapExpectedError(error, {}), error);
  assert.equal(
    new ApiError(400, { detail: "Direct message" }).message,
    "Direct message",
  );
  assert.equal(new ApiError(500, null).message, "An unknown error occurred.");
});
