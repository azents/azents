import assert from "node:assert/strict";
import test from "node:test";
import {
  admittedBrowserProfile,
  decodeMainBinding,
  encodeMainBinding,
} from "./runtime-web-auth-policy.ts";

void test("requires matching Chromium client-hint and user-agent versions", () => {
  const request = new Request("https://app.example.com/runtime-web/auth", {
    headers: {
      "Sec-CH-UA": '"Chromium";v="152", "Not_A Brand";v="99"',
      "User-Agent":
        "Mozilla/5.0 AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    },
  });
  assert.equal(admittedBrowserProfile(request), "chromium-152");

  const mismatch = new Request("https://app.example.com/runtime-web/auth", {
    headers: {
      "Sec-CH-UA": '"Chromium";v="152"',
      "User-Agent": "Mozilla/5.0 Chrome/151.0.0.0 Safari/537.36",
    },
  });
  assert.equal(admittedBrowserProfile(mismatch), null);
});

void test("encodes and validates the host-only Main binding cookie", () => {
  const initiationId = "initiation0000000000000000000000";
  const secret = "secret000000000000000000000000000000";
  const encoded = encodeMainBinding(initiationId, secret);
  assert.deepEqual(decodeMainBinding(encoded), { initiationId, secret });
  assert.equal(decodeMainBinding(`short.${secret}`), null);
  assert.equal(decodeMainBinding(`${initiationId}.short`), null);
});
