import assert from "node:assert/strict";
import test from "node:test";
import { parseExternalAccountOAuthCallbackQuery } from "./oauth-callback-query.ts";

void test("accepts one bounded authorization code and state", () => {
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({
      code: "authorization-code",
      state: "opaque-state",
    }),
    {
      type: "EXCHANGE",
      code: "authorization-code",
      state: "opaque-state",
    },
  );
});

void test("classifies bounded provider cancellation without retaining callback data", () => {
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({
      error: "access_denied",
      state: "opaque-state",
    }),
    { type: "CANCELLED" },
  );
});

void test("classifies other bounded provider errors without exposing their text", () => {
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({
      error: "provider-specific-private-detail",
      state: "opaque-state",
    }),
    { type: "PROVIDER_REJECTED" },
  );
});

void test("rejects duplicate, empty, missing, and oversized callback values", () => {
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({
      code: ["first", "second"],
      state: "opaque-state",
    }),
    { type: "INVALID" },
  );
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({ code: "", state: "opaque-state" }),
    { type: "INVALID" },
  );
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({ code: "authorization-code" }),
    { type: "INVALID" },
  );
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({
      code: "authorization-code",
      state: "x".repeat(1025),
    }),
    { type: "INVALID" },
  );
  assert.deepEqual(
    parseExternalAccountOAuthCallbackQuery({
      error: "x".repeat(257),
    }),
    { type: "INVALID" },
  );
});
