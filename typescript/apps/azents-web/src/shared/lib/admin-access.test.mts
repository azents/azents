import assert from "node:assert/strict";
import test from "node:test";
import { getAdminWebUrl } from "./admin-access.ts";

await test("system administrators receive the configured Admin Web URL", () => {
  assert.equal(
    getAdminWebUrl("https://admin.example.test/console", ["system_admin"]),
    "https://admin.example.test/console",
  );
});

await test("ordinary users do not receive the Admin Web URL", () => {
  assert.equal(getAdminWebUrl("https://admin.example.test/console", []), null);
});

await test("the link remains hidden when no Admin Web URL is configured", () => {
  assert.equal(getAdminWebUrl(null, ["system_admin"]), null);
});
