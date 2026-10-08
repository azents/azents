import assert from "node:assert/strict";
import test from "node:test";
import {
  consumeGitHubUserPopupHandoff,
  decodeGitHubUserCompletion,
  deserializeGitHubUserContext,
  GITHUB_USER_COMPLETION_EVENT,
  githubUserErrorReason,
  isGitHubUserMode,
  mergeGitHubUserAccess,
  parseGitHubUserState,
} from "./github-user-oauth-state.ts";
import type { GitHubUserPopupHandoff } from "./github-user-oauth-state.ts";
import type {
  GitHubUserInstallation,
  GitHubUserRepository,
} from "@azents/public-client";

for (const closed of [false, true]) {
  void test(`accepted popup cannot replay on Details reopen (closed=${closed})`, () => {
    const originalPopup = { closed };
    let pending: GitHubUserPopupHandoff<typeof originalPopup> | null = {
      toolkitId: "toolkit",
      popup: originalPopup,
    };
    const activePopup = pending.popup;
    pending = consumeGitHubUserPopupHandoff(pending, activePopup);
    assert.equal(pending, null);
    assert.equal(activePopup, originalPopup);
    // Both completion and cancellation may unmount Details; neither restores
    // its consumed initial handoff when the manager opens Details again.
    assert.equal(consumeGitHubUserPopupHandoff(pending, activePopup), null);
    const freshPopup = { closed: false };
    pending = { toolkitId: "toolkit", popup: freshPopup };
    assert.equal(
      consumeGitHubUserPopupHandoff(pending, originalPopup),
      pending,
    );
    pending = consumeGitHubUserPopupHandoff(pending, freshPopup);
    assert.equal(pending, null);
    assert.equal(consumeGitHubUserPopupHandoff(pending, freshPopup), null);
  });
}

void test("fixed GitHub user state cannot enter the old installation relay", () => {
  assert.equal(
    parseGitHubUserState("github_user.attempt_123.nonce-123"),
    "attempt_123",
  );
  for (const state of [
    null,
    "",
    "github.attempt.nonce",
    "github_user.a",
    "github_user..nonce",
    "github_user.a.",
    "github_user.a.b.extra",
    "github_user.a/b.nonce",
  ]) {
    assert.equal(parseGitHubUserState(state), null);
  }
});
void test("origin context keeps exact ownership and return view without OAuth material", () => {
  const context = {
    handle: "team",
    toolkitId: "tk",
    agentId: "agent",
    returnPath: "/w/team/agents/agent/settings/capabilities#agent-toolkits",
    returnView: "DETAIL",
  };
  assert.deepEqual(
    deserializeGitHubUserContext(JSON.stringify(context)),
    context,
  );
  for (const value of [
    void 0,
    "not-json",
    JSON.stringify({ ...context, code: "secret" }),
    JSON.stringify({ ...context, returnPath: "https://evil.example" }),
    JSON.stringify({ ...context, agentId: "" }),
  ]) {
    assert.equal(deserializeGitHubUserContext(value), null);
  }
});
void test("completion requires same origin, exact non-null popup and current attempt, with no extra payload", () => {
  const popup = {};
  const event = {
    origin: "https://azents.example",
    source: popup,
    data: { type: GITHUB_USER_COMPLETION_EVENT, attempt_id: "attempt" },
  };
  assert.equal(
    decodeGitHubUserCompletion(event, event.origin, popup, "attempt"),
    true,
  );
  assert.equal(
    decodeGitHubUserCompletion(event, event.origin, null, "attempt"),
    false,
  );
  assert.equal(
    decodeGitHubUserCompletion(event, event.origin, popup, null),
    false,
  );
  assert.equal(
    decodeGitHubUserCompletion(event, event.origin, popup, "old"),
    false,
  );
  assert.equal(
    decodeGitHubUserCompletion(
      { ...event, source: {} },
      event.origin,
      popup,
      "attempt",
    ),
    false,
  );
  assert.equal(
    decodeGitHubUserCompletion(
      { ...event, origin: "https://other.example" },
      event.origin,
      popup,
      "attempt",
    ),
    false,
  );
  for (const data of [
    null,
    { type: "azents-oauth-callback", success: true },
    { ...event.data, code: "secret" },
    { ...event.data, state: "secret" },
    { ...event.data, account_login: "untrusted" },
  ]) {
    assert.equal(
      decodeGitHubUserCompletion(
        { ...event, data },
        event.origin,
        popup,
        "attempt",
      ),
      false,
    );
  }
});
function repo(id: number): GitHubUserRepository {
  return {
    repository_id: id,
    owner_login: "personal",
    name: `repo-${id}`,
    full_name: `personal/repo-${id}`,
    private: true,
    permissions: { read: true, write: null, admin: null },
  };
}
function owner(
  id: number,
  repositories: GitHubUserRepository[],
  complete: boolean,
): GitHubUserInstallation {
  return {
    installation_id: id,
    app_id: 42,
    account_login: `owner-${id}`,
    account_type: id === 1 ? "User" : "Organization",
    account_avatar_url: null,
    app_permissions: { contents: "read" },
    repositories,
    repositories_complete: complete,
    failure_reason: null,
  };
}
void test("pagination merges personal and multiple orgs, including repeated owner pages in one response", () => {
  const merged = mergeGitHubUserAccess(
    [owner(1, [repo(1)], false)],
    [
      owner(1, [repo(1), repo(2)], false),
      owner(1, [repo(3)], true),
      owner(2, [], true),
      { ...owner(3, [], false), failure_reason: "target_denied" },
    ],
  );
  assert.equal(merged.length, 3);
  assert.deepEqual(
    merged[0]?.repositories.map((value) => value.repository_id),
    [1, 2, 3],
  );
  assert.equal(merged[0].repositories_complete, true);
  assert.ok(merged[2]);
  assert.equal(merged[2].failure_reason, "target_denied");
  const firstRepository = merged[0].repositories[0];
  assert.ok(firstRepository);
  assert.equal(firstRepository.permissions.write, null);
});
void test("a later denied page retains known repositories and partial readiness", () => {
  const merged = mergeGitHubUserAccess(
    [owner(1, [repo(1)], false)],
    [{ ...owner(1, [], false), failure_reason: "provider_unavailable" }],
  );
  assert.equal(merged[0]?.repositories.length, 1);
  assert.equal(merged[0].repositories_complete, false);
});
void test("only new GitHub variants use persistent user OAuth", () => {
  for (const mode of ["github_app_user", "github_app_platform_user"]) {
    assert.equal(isGitHubUserMode(mode), true);
  }
  for (const mode of [
    "pat",
    "github_app",
    "github_app_platform",
    "oauth2",
    null,
  ]) {
    assert.equal(isGitHubUserMode(mode), false);
  }
});
void test("safe backend error codes select recovery copy without provider bodies", () => {
  assert.equal(
    githubUserErrorReason(
      { data: { apiError: { code: "unexpected" } } },
      "setupFailed",
    ),
    "setupFailed",
  );
  assert.equal(
    githubUserErrorReason(
      { data: { apiError: { code: "stale" } } },
      "setupFailed",
    ),
    "stale",
  );
  assert.equal(
    githubUserErrorReason(
      { data: { apiError: { code: "authority" } } },
      "setupFailed",
    ),
    "authority",
  );
  assert.equal(
    githubUserErrorReason(
      { data: { apiError: { code: "invalid" } } },
      "setupFailed",
    ),
    "incompatible",
  );
  assert.equal(
    githubUserErrorReason(new Error("private provider text"), "setupFailed"),
    "setupFailed",
  );
});
