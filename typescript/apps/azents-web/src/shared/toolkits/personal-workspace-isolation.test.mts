import assert from "node:assert/strict";
import { test } from "node:test";
import {
  creationReturnPath,
  deserializeGitHubUserCreation,
  gitHubCreationMatches,
} from "./github-user-creation-state.ts";
import {
  gitHubUserResumeMatches,
  parseGitHubUserContext,
} from "./github-user-oauth-state.ts";
import {
  decodeGoogleResume,
  googleResumeMatches,
  googleReturnPath,
} from "./google-resume.ts";
import {
  decodeMcpCallbackTarget,
  mcpCallbackReturnPath,
} from "./mcp-callback-target.ts";
import {
  personalToolkitAgentInput,
  personalToolkitCreateInput,
  personalToolkitSavedInput,
  personalToolkitScopeInput,
} from "./personal-toolkit-inputs.ts";
import { toolkitManagementPath } from "./toolkit-owner-scope.ts";

void test("Every personal management input requires explicit Workspace routing metadata", () => {
  for (const [schema, fields] of [
    [personalToolkitScopeInput, {}],
    [personalToolkitSavedInput, { toolkitId: "same-toolkit" }],
    [personalToolkitAgentInput, { agentId: "same-agent" }],
    [personalToolkitCreateInput, { toolkitType: "mcp", config: {} }],
  ] as const) {
    assert.equal(schema.safeParse(fields).success, false);
    assert.equal(
      schema.safeParse({ ...fields, handle: "workspace-a" }).success,
      true,
    );
    assert.equal(schema.safeParse({ ...fields, handle: "" }).success, false);
    assert.equal(
      schema.safeParse({
        ...fields,
        handle: "workspace-a",
        ownerUserId: "foreign",
      }).success,
      false,
    );
  }
});

void test("Same account and Toolkit identity cannot resume Google or GitHub from another Workspace", () => {
  const a = { owner: "user", handle: "workspace-a" } as const;
  const b = { owner: "user", handle: "workspace-b" } as const;
  const google = decodeGoogleResume({
    ...a,
    toolkitId: "same-toolkit",
    attemptId: "attempt",
    expiresAt: "2099-01-01T00:00:00Z",
    stateDigest: "a".repeat(64),
    phase: "AUTHORIZING",
    returnPath: googleReturnPath(a, "same-toolkit"),
  });
  assert.ok(google);
  assert.equal(googleResumeMatches(google, a, "same-toolkit"), true);
  assert.equal(googleResumeMatches(google, b, "same-toolkit"), false);
  assert.equal(decodeGoogleResume({ ...google, handle: b.handle }), null);
  const creation = deserializeGitHubUserCreation(
    JSON.stringify({
      ...a,
      attemptId: "attempt",
      phase: "AUTHORIZING",
      returnPath: creationReturnPath(a),
    }),
  );
  assert.ok(creation);
  assert.equal(gitHubCreationMatches(creation, b), false);
  assert.equal(
    deserializeGitHubUserCreation(
      JSON.stringify({ ...creation, handle: b.handle }),
    ),
    null,
  );
  const saved = parseGitHubUserContext({
    ...a,
    toolkitId: "same-toolkit",
    reviewAttemptId: "attempt",
    returnView: "EDIT",
    returnPath: toolkitManagementPath(a, "same-toolkit"),
  });
  assert.ok(saved);
  assert.equal(
    gitHubUserResumeMatches(saved, {
      ...saved,
      ...b,
      returnPath: toolkitManagementPath(b, "same-toolkit"),
    }),
    false,
  );
});

void test("Personal MCP callback keeps required Workspace and rejects repeated or mixed targets", () => {
  const target = decodeMcpCallbackTarget({
    handle: "workspace-a",
    personal_toolkit_config_id: "saved",
  });
  assert.ok(target);
  assert.equal(
    mcpCallbackReturnPath(target),
    "/w/workspace-a/personal-tools/saved/edit",
  );
  const invalid: Array<Record<string, string | string[] | null>> = [
    { personal_toolkit_config_id: "saved" },
    {
      handle: ["workspace-a", "workspace-b"],
      personal_toolkit_config_id: "saved",
    },
    {
      handle: "workspace-a",
      personal_toolkit_config_id: "saved",
      toolkit_config_id: "shared",
    },
    {
      handle: "workspace-a",
      personal_toolkit_config_id: "saved",
      agent_id: "agent",
    },
  ];
  for (const query of invalid) {
    assert.equal(decodeMcpCallbackTarget(query), null);
  }
});
