import assert from "node:assert/strict";
import test from "node:test";
import { browserSocketUrl } from "./socketUrl.ts";

void test("Browser socket uses the ordinary public API origin without URI credentials", () => {
  const resource = { handle: "team", agentId: "agent", sessionId: "session" };
  assert.equal(
    browserSocketUrl(
      "https://api.example.test/api?ticket=discard#discard",
      resource,
    ),
    "wss://api.example.test/api/browser/v1/workspaces/team/agents/agent/sessions/session/ws",
  );
  assert.equal(
    browserSocketUrl("http://localhost:8010/", {
      ...resource,
      handle: "with space",
    }),
    "ws://localhost:8010/browser/v1/workspaces/with%20space/agents/agent/sessions/session/ws",
  );
  assert.throws(() => browserSocketUrl("ftp://example.test", resource));
  assert.throws(() =>
    browserSocketUrl("https://user:password@example.test", resource),
  );
});
