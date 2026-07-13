import assert from "node:assert/strict";
import test from "node:test";
import {
  getAuthCookiePath,
  getPublicRoutePath,
  getPublicRouteUrl,
  isExpectedOrigin,
} from "./auth-policy.ts";

await test("Admin auth cookie path follows the configured public base path", () => {
  assert.equal(getAuthCookiePath("https://admin.example.com"), "/");
  assert.equal(getAuthCookiePath("https://example.com/admin"), "/admin");
  assert.equal(getAuthCookiePath("https://example.com/admin/"), "/admin");
});

await test("public routes stay inside the configured Admin Web base path", () => {
  assert.equal(
    getPublicRoutePath("https://example.com/admin", "/api/session"),
    "/admin/api/session",
  );
  assert.equal(
    getPublicRouteUrl("https://example.com/admin/", "/api/trpc"),
    "https://example.com/admin/api/trpc",
  );
  assert.equal(
    getPublicRoutePath("https://admin.example.com", "/login"),
    "/login",
  );
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
