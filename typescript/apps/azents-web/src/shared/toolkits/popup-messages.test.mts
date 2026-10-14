import assert from "node:assert/strict";
import test from "node:test";
import {
  decodeGitHubPopupMessage,
  decodeOAuthCallbackMessage,
} from "./popup-messages.ts";

const origin = "https://azents.example";
const popup = {};
function github(data: unknown): ReturnType<typeof decodeGitHubPopupMessage> {
  return decodeGitHubPopupMessage(
    { data, origin, source: popup },
    origin,
    popup,
    true,
  );
}
void test("current producer-shaped GitHub installation/code handoffs retain forward extensions", () => {
  assert.deepEqual(
    github({
      type: "azents-github-app-installed",
      installation_id: "42",
      future: { version: 2 },
    }),
    { type: "azents-github-app-installed" },
  );
  assert.deepEqual(
    github({
      type: "azents-github-installations-code",
      code: "code",
      state: "state",
      future: null,
    }),
    { type: "azents-github-installations-code", code: "code", state: "state" },
  );
  assert.deepEqual(
    github({ type: "azents-github-installations-code", code: "", state: "" }),
    { type: "azents-github-installations-code", code: "", state: "" },
  );
  assert.deepEqual(github({ type: "azents-github-app-installed" }), {
    type: "azents-github-app-installed",
  });
});
void test("GitHub control ingress ignores malformed records and preserves exact source/origin/epoch guards", () => {
  for (const data of [
    null,
    [],
    1,
    "event",
    { type: "other" },
    { type: "azents-github-installations-code" },
    { type: "azents-github-installations-code", code: null, state: "state" },
    { type: "azents-github-installations-code", code: "code", state: 3 },
  ]) {
    assert.equal(github(data), null);
  }
  const event = {
    data: { type: "azents-github-app-installed", installation_id: "42" },
    origin,
    source: popup,
  };
  assert.equal(
    decodeGitHubPopupMessage(
      { ...event, origin: "https://other.example" },
      origin,
      popup,
      true,
    ),
    null,
  );
  assert.equal(
    decodeGitHubPopupMessage({ ...event, source: {} }, origin, popup, true),
    null,
  );
  assert.equal(decodeGitHubPopupMessage(event, origin, null, true), null);
  assert.equal(decodeGitHubPopupMessage(event, origin, popup, false), null);
});
void test("MCP success/error callbacks trigger authoritative refresh without requiring ignored producer fields", () => {
  for (const data of [
    { type: "azents-oauth-callback", success: true },
    {
      type: "azents-oauth-callback",
      success: false,
      message: "Denied",
      error: null,
    },
    { type: "azents-oauth-callback" },
    { type: "azents-oauth-callback", success: null, future: [1] },
  ]) {
    assert.deepEqual(decodeOAuthCallbackMessage({ origin, data }, origin), {
      type: "azents-oauth-callback",
    });
  }
  for (const data of [null, [], "azents-oauth-callback", { type: "other" }]) {
    assert.equal(decodeOAuthCallbackMessage({ origin, data }, origin), null);
  }
  assert.equal(
    decodeOAuthCallbackMessage(
      {
        origin: "https://other.example",
        data: { type: "azents-oauth-callback", success: true },
      },
      origin,
    ),
    null,
  );
});
