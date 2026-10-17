import assert from "node:assert/strict";
import { test } from "node:test";
import {
  creationReturnPath,
  deserializeGitHubUserCreation,
  gitHubCreationMatches,
  gitHubCreationScope,
  parseGitHubCreationState,
} from "../../shared/toolkits/github-user-creation-state.ts";

void test("only nonsecret exact creation context is persisted", () => {
  const context = {
    handle: "acme",
    agentId: "agent",
    attemptId: "attempt",
    phase: "REVIEW",
    returnPath: creationReturnPath({ handle: "acme", agentId: "agent" }),
  };
  assert.deepEqual(
    deserializeGitHubUserCreation(JSON.stringify(context)),
    context,
  );
  for (const extra of [
    { code: "code" },
    { credentials: {} },
    { token: "token" },
    { returnPath: "/w/other/toolkits/new" },
    { returnPath: "https://example.com" },
    { toolkitId: "saved" },
  ]) {
    assert.equal(
      deserializeGitHubUserCreation(JSON.stringify({ ...context, ...extra })),
      null,
    );
  }
});
void test("Personal GitHub creation resumes only its account target and exact return", () => {
  const context = {
    owner: "user",
    handle: "workspace",
    attemptId: "personal",
    phase: "AUTHORIZING",
    returnPath: creationReturnPath({ owner: "user", handle: "workspace" }),
  };
  const decoded = deserializeGitHubUserCreation(JSON.stringify(context));
  assert.ok(decoded);
  assert.deepEqual(gitHubCreationScope(decoded), {
    owner: "user",
    handle: "workspace",
  });
  assert.ok(
    gitHubCreationMatches(decoded, { owner: "user", handle: "workspace" }),
  );
  assert.equal(gitHubCreationMatches(decoded, { handle: "team" }), false);
  for (const invalid of [
    { handle: "workload" },
    { agentId: "agent" },
    { userId: "foreign" },
    { returnPath: "/w/team/toolkits/new" },
    { returnPath: "/w/workspace/personal-tools/other/edit" },
    { code: "fixture-code" },
    { state: "fixture-state" },
  ]) {
    assert.equal(
      deserializeGitHubUserCreation(JSON.stringify({ ...context, ...invalid })),
      null,
    );
  }
});
void test("creation state cannot be interpreted as a saved Toolkit reconnect", () => {
  assert.equal(
    parseGitHubCreationState("github_user_create.attempt.nonce"),
    "attempt",
  );
  for (const state of [
    null,
    "github_user.attempt.nonce",
    "github_user_create.attempt",
    "github_user_create.a/b.nonce",
    "github_user_create.attempt.nonce.extra",
  ]) {
    assert.equal(parseGitHubCreationState(state), null);
  }
});
