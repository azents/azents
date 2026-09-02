import assert from "node:assert/strict";
import test from "node:test";
import {
  getAuthCookiePath,
  getNativeLoginUrl,
  getNativePostLoginUrl,
  getNativePublicRouteUrl,
  getPublicRoutePath,
  getPublicRouteUrl,
  isExpectedOrigin,
  isPublicRouteUrl,
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

await test("path-prefixed auth navigation requires an absolute browser URL", () => {
  assert.equal(
    getNativePublicRouteUrl("https://example.com/admin", "/workspaces"),
    "https://example.com/admin/workspaces",
  );
  assert.equal(
    getNativePublicRouteUrl("https://admin.example.com", "/workspaces"),
    null,
  );
});

await test("path-prefixed login preserves only safe public return paths", () => {
  assert.equal(
    getNativeLoginUrl(
      "https://example.com/console",
      "https://example.com/console/users?page=2#details",
    ),
    "https://example.com/console/login?returnTo=%2Fconsole%2Fusers%3Fpage%3D2%23details",
  );
  assert.equal(
    getNativeLoginUrl(
      "https://example.com/console",
      "https://attacker.example/console/users",
    ),
    "https://example.com/console/login",
  );
  assert.equal(
    getNativeLoginUrl(
      "https://example.com/console",
      "https://example.com/console/login?returnTo=%2Fconsole%2Fusers",
    ),
    null,
  );
  assert.equal(
    getNativePostLoginUrl(
      "https://example.com/console",
      "https://example.com/console/login?returnTo=%2Fconsole%2Fusers%3Fpage%3D2%23details",
    ),
    "https://example.com/console/users?page=2#details",
  );
  assert.equal(
    getNativePostLoginUrl(
      "https://example.com/console",
      "https://example.com/console/login?returnTo=https%3A%2F%2Fattacker.example%2F",
    ),
    "https://example.com/console/workspaces",
  );
  assert.equal(
    getNativePostLoginUrl(
      "https://example.com/console",
      "https://example.com/console/login?returnTo=http%3A%2F%2F%5B",
    ),
    "https://example.com/console/workspaces",
  );
});

await test("public route matching ignores query strings without crossing origins", () => {
  assert.equal(
    isPublicRouteUrl(
      "https://example.com/console",
      "https://example.com/console/login?returnTo=%2Fconsole%2Fusers",
      "/login",
    ),
    true,
  );
  assert.equal(
    isPublicRouteUrl(
      "https://example.com/console",
      "https://attacker.example/console/login",
      "/login",
    ),
    false,
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
