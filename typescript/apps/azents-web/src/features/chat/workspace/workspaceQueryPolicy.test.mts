import assert from "node:assert/strict";
import test from "node:test";

import { shouldQueryProjectBrowserManifest } from "./workspaceQueryPolicy.ts";

void test("loads the Project Browser Manifest only for a ready workspace", () => {
  assert.equal(shouldQueryProjectBrowserManifest("READY"), true);
  assert.equal(shouldQueryProjectBrowserManifest("UNAVAILABLE"), false);
  assert.equal(shouldQueryProjectBrowserManifest("CONNECTING"), false);
  assert.equal(shouldQueryProjectBrowserManifest(null), false);
});
