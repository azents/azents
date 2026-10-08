import assert from "node:assert/strict";
import { test } from "node:test";
import {
  creationReturnPath,
  deserializeGitHubUserCreation,
  parseGitHubCreationState,
} from "./github-user-creation-state.ts";

void test("only nonsecret exact creation context is persisted", () => {
  const context = {
    handle: "acme",
    agentId: "agent",
    attemptId: "attempt",
    phase: "REVIEW",
    returnPath: creationReturnPath("acme", "agent"),
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
