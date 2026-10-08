import assert from "node:assert/strict";
import test from "node:test";
import {
  runtimeWebLoginNextWithFragment,
  runtimeWebReturnDestination,
  runtimeWebReturnTarget,
  runtimeWebReturnTargetWithFragment,
} from "./runtime-web-return-target.ts";

for (const target of [
  "/",
  "/catalog/%E2%9C%93?tag=one&tag=two&next=%2Fbasket#details",
]) {
  void test(`preserves navigation target ${target}`, () => {
    assert.equal(runtimeWebReturnTarget(target), target);
    assert.equal(
      runtimeWebReturnDestination("https://service.test/", target),
      `https://service.test${target}`,
    );
  });
}

for (const target of [
  null,
  "",
  "https://evil.test/",
  "//evil.test/",
  "/\\evil.test/",
  "/\nfoo",
  "/\rfoo",
  "/\u0000foo",
  "/ foo",
]) {
  void test(`rejects an unsafe target ${JSON.stringify(target)}`, () => {
    assert.equal(runtimeWebReturnTarget(target), null);
    if (typeof target === "string") {
      assert.throws(() =>
        runtimeWebReturnDestination("https://service.test/", target),
      );
    }
  });
}

void test("preserves fragment once across authentication and activation", () => {
  assert.equal(
    runtimeWebReturnTargetWithFragment("/catalog?view=grid", "#details"),
    "/catalog?view=grid#details",
  );
  assert.equal(
    runtimeWebReturnTargetWithFragment("/catalog#details", "#another"),
    "/catalog#details",
  );
});

void test("carries the service fragment through Main Web login without changing other login destinations", () => {
  const next = `/runtime-web/auth?${new URLSearchParams({ service_id: "s".repeat(32), return_to: "/catalog?view=grid" })}`;
  const result = runtimeWebLoginNextWithFragment(next, "#details");
  assert.ok(result);
  const url = new URL(result, "https://main.test");
  assert.equal(url.pathname, "/runtime-web/auth");
  assert.equal(url.searchParams.get("return_to"), "/catalog?view=grid#details");
  assert.equal(
    runtimeWebLoginNextWithFragment("/workspaces?view=grid", "#details"),
    "/workspaces?view=grid",
  );
  assert.equal(runtimeWebLoginNextWithFragment(null, "#details"), null);
  assert.equal(runtimeWebLoginNextWithFragment(next, ""), next);
});
