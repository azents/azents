import assert from "node:assert/strict";
import test from "node:test";
import {
  creationReturnPath,
  deserializeGitHubUserCreation,
} from "./github-user-creation-state.ts";
import { decodeGoogleResume, googleReturnPath } from "./google-resume.ts";
import {
  isToolkitManagementPath,
  toolkitManagementPath,
} from "./toolkit-owner-scope.ts";

void test("Personal Provider resumes preserve exact same-Workspace Agent and conversation identity", () => {
  const scope = { owner: "user", handle: "research" } as const;
  const origin = {
    handle: "research",
    agentId: "assistant",
    sessionId: "conversation",
  };
  const path = toolkitManagementPath(scope, null, origin);
  assert.equal(
    path,
    "/w/research/personal-tools/new?originHandle=research&originAgentId=assistant&originSession=conversation",
  );
  assert.equal(creationReturnPath(scope, origin), path);
  assert.equal(googleReturnPath(scope, void 0, origin), path);
  const github = {
    ...scope,
    attemptId: "attempt-a",
    phase: "AUTHORIZING",
    returnPath: path,
  };
  assert.deepEqual(
    deserializeGitHubUserCreation(JSON.stringify(github)),
    github,
  );
  const google = {
    ...scope,
    attemptId: "attempt-a",
    phase: "AUTHORIZING",
    returnPath: path,
    expiresAt: "2026-10-18T00:00:00Z",
    stateDigest: "a".repeat(64),
  };
  assert.deepEqual(decodeGoogleResume(google), google);
});

void test("Resume navigation rejects foreign Workspaces, arbitrary redirects and ambiguous origin query", () => {
  const scope = { owner: "user", handle: "research" } as const;
  const base = toolkitManagementPath(scope, null);
  for (const path of [
    "https://foreign.test/",
    "//foreign.test/",
    "/w/foreign/personal-tools/new",
    `${base}?originHandle=foreign&originAgentId=assistant`,
    `${base}?originHandle=research&originAgentId=..`,
    `${base}?originHandle=research&originAgentId=assistant&returnTo=https://foreign.test`,
    `${base}?originHandle=research&originAgentId=assistant&originAgentId=other`,
    `${base}?originHandle=research&originAgentId=assistant&originSession=%2Foutside`,
  ]) {
    assert.equal(isToolkitManagementPath(scope, null, path), false, path);
    assert.equal(
      deserializeGitHubUserCreation(
        JSON.stringify({
          ...scope,
          attemptId: "attempt",
          phase: "AUTHORIZING",
          returnPath: path,
        }),
      ),
      null,
    );
  }
  assert.equal(
    toolkitManagementPath(scope, null, {
      handle: "foreign",
      agentId: "assistant",
    }),
    base,
  );
});
