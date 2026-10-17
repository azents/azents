import assert from "node:assert/strict";
import test from "node:test";
import {
  agentPersonalToolsPath,
  parseOriginSession,
  parsePersonalToolsOrigin,
  personalToolsSetupPath,
} from "./navigation.ts";

void test("Personal setup and Agent access retain the originating conversation", () => {
  const origin = parsePersonalToolsOrigin({
    originHandle: "research",
    originAgentId: "agent-a",
    originSession: "session-a",
  });
  assert.ok(origin);
  assert.equal(
    agentPersonalToolsPath(origin),
    "/w/research/agents/agent-a/personal-tools?originSession=session-a",
  );
  assert.equal(
    personalToolsSetupPath(origin),
    "/w/research/personal-tools/new?originHandle=research&originAgentId=agent-a&originSession=session-a",
  );
});

void test("Personal setup origin is exact Agent identity, not an arbitrary return URL or owner", () => {
  const origin = parsePersonalToolsOrigin({
    originHandle: "research",
    originAgentId: "agent-a",
    returnTo: "https://foreign.test",
  });
  assert.deepEqual(origin, { handle: "research", agentId: "agent-a" });
  assert.ok(origin);
  assert.equal(
    agentPersonalToolsPath(origin),
    "/w/research/agents/agent-a/personal-tools",
  );
  assert.equal(
    personalToolsSetupPath(origin),
    "/w/research/personal-tools/new?originHandle=research&originAgentId=agent-a",
  );
});

void test("Mixed, repeated, missing and path-escaping origin values never become navigation targets", () => {
  for (const query of [
    {},
    { originHandle: "research" },
    { originHandle: ["research"], originAgentId: "agent" },
    { originHandle: "..", originAgentId: "agent" },
    { originHandle: "research", originAgentId: "//foreign.test" },
    { originHandle: "research", originAgentId: "%2foutside" },
    { originHandle: "research", originAgentId: "agent?owner=foreign" },
  ]) {
    assert.equal(parsePersonalToolsOrigin(query), null);
  }
  for (const value of [
    ["session-a"],
    "../outside",
    "https://foreign.test",
    null,
  ]) {
    assert.equal(parseOriginSession(value), null);
  }
  assert.equal(parseOriginSession("session-a"), "session-a");
});
