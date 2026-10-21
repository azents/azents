import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ADMIN_RESOURCES,
  adminNavigation,
  adminRouteMatches,
  SETTINGS_SECTIONS,
} from "./admin-navigation.ts";

void test("every existing Admin destination is reachable from one grouped navigation", () => {
  const { groups } = adminNavigation(
    "https://admin.example.invalid/",
    "/users",
    null,
  );
  assert.deepEqual(
    groups.map((group) => group.label),
    ["People & access", "Platform", "Settings", "Diagnostics"],
  );
  const items = groups.flatMap((group) => group.items);
  assert.equal(new Set(items.map((item) => item.href)).size, items.length);
  for (const resource of ADMIN_RESOURCES) {
    if (resource.name === "system-settings") {
      for (const section of SETTINGS_SECTIONS) {
        assert.ok(
          items.some(
            (item) => item.href === `/system-settings?section=${section.value}`,
          ),
        );
      }
    } else {
      assert.ok(items.some((item) => item.href === resource.list));
    }
  }
});

void test("settings location and the single active link follow the selected query", () => {
  for (const section of SETTINGS_SECTIONS) {
    const { groups, location } = adminNavigation(
      "https://example.invalid/admin",
      "/admin/system-settings",
      section.value,
    );
    const active = groups
      .flatMap((group) => group.items)
      .filter((item) => item.active);
    assert.equal(active.length, 1);
    assert.equal(
      active[0]?.href,
      `/admin/system-settings?section=${section.value}`,
    );
    assert.deepEqual(location, { group: "Settings", label: section.label });
  }
});

void test("cross-route and in-page query links have the same canonical settings destinations", () => {
  const fromUsers = adminNavigation(
    "https://example.invalid/",
    "/users",
    null,
  ).groups.find((group) => group.label === "Settings");
  const fromSettings = adminNavigation(
    "https://example.invalid/",
    "/system-settings",
    "github",
  ).groups.find((group) => group.label === "Settings");
  assert.deepEqual(
    fromUsers?.items.map((item) => item.href),
    fromSettings?.items.map((item) => item.href),
  );
});

void test("nested detail routes retain their parent location without matching unrelated prefixes", () => {
  const { groups, location } = adminNavigation(
    "https://example.invalid/admin",
    "/admin/workspaces/sample/runtime-profiles/p1",
    null,
  );
  assert.deepEqual(location, { group: "People & access", label: "Workspaces" });
  assert.equal(
    groups.flatMap((group) => group.items).filter((item) => item.active).length,
    1,
  );
  assert.equal(adminRouteMatches("/users-extra", "/users"), false);
  assert.equal(adminRouteMatches("/users/u1", "/users"), true);
});

void test("base-prefixed and native Admin routes resolve to the same destinations", () => {
  for (const resource of ADMIN_RESOURCES) {
    const prefixed = adminNavigation(
      "https://example.invalid/gateway/admin/",
      `/gateway/admin${resource.list}`,
      null,
    );
    const native = adminNavigation(
      "https://example.invalid/gateway/admin/",
      resource.list,
      null,
    );
    assert.deepEqual(prefixed, native);
    const active = prefixed.groups
      .flatMap((group) => group.items)
      .filter((item) => item.active);
    assert.equal(active.length, 1);
    assert.ok(active[0]?.href.startsWith("/gateway/admin/"));
  }
});
