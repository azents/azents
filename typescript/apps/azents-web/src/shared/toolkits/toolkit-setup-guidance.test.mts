import assert from "node:assert/strict";
import test from "node:test";
import {
  getToolkitSetupGuide,
  toolkitSetupGuides,
} from "./toolkit-setup-guidance.ts";

void test("all currently registered production providers have specific preparation guidance", () => {
  for (const provider of [
    "mcp",
    "github",
    "notion",
    "sentry",
    "gcp",
    "aws",
    "google_analytics",
    "google",
    "brave_search",
    "kubernetes",
    "envvar",
  ]) {
    assert.equal(getToolkitSetupGuide(provider), provider);
  }
});
void test("unknown catalog types retain generic guidance without pretending availability", () => {
  assert.equal(getToolkitSetupGuide("runtime_hook_qa"), "other");
  assert.equal(getToolkitSetupGuide(""), "other");
  assert.equal(getToolkitSetupGuide("constructor"), "other");
  assert.equal(getToolkitSetupGuide("__proto__"), "other");
});
void test("help links contain only public HTTPS documentation without credential-bearing parameters", () => {
  for (const guide of Object.values(toolkitSetupGuides)) {
    if (guide.docs == null) {
      continue;
    }
    const url = new URL(guide.docs);
    assert.equal(url.protocol, "https:");
    assert.equal(url.username, "");
    assert.equal(url.password, "");
    assert.equal(url.search, "");
  }
});
