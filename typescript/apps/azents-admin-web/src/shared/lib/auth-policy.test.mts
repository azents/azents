import assert from "node:assert/strict";
import test from "node:test";
import { getAuthCookiePath, isExpectedOrigin } from "./auth-policy.ts";

await test("Admin auth cookie path follows the configured public base path", () => {
  assert.equal(getAuthCookiePath("https://admin.example.com"), "/");
  assert.equal(getAuthCookiePath("https://example.com/admin"), "/admin");
  assert.equal(getAuthCookiePath("https://example.com/admin/"), "/admin");
});

await test("same-origin policy accepts only the configured public origin", () => {
  assert.equal(
    isExpectedOrigin("https://example.com", "https://example.com/admin"),
    true,
  );
  assert.equal(
    isExpectedOrigin("https://attacker.example", "https://example.com/admin"),
    false,
  );
  assert.equal(isExpectedOrigin(null, "https://example.com/admin"), false);
  assert.equal(
    isExpectedOrigin("not-a-url", "https://example.com/admin"),
    false,
  );
});
