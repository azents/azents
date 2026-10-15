import assert from "node:assert/strict";
import { test } from "node:test";
import { projectPlatformGitHubCandidateImpact } from "./platform-github-impact.ts";

const producerImpact = {
  app_id_changed: true,
  affected_user_count: 3,
  affected_installation_count: 4,
  affected_toolkit_count: 5,
  affected_agent_count: 6,
  current_app_id_source: "admin",
  confirmation_actions: ["activate", "reconnect"],
  confirmation_required: true,
};

void test("projects all interpreted fields from the current producer without mutating opaque extensions", () => {
  const extension = { future: { nullable: null, entries: [1, "opaque"] } };
  const original = { ...producerImpact, extension };
  const projected = projectPlatformGitHubCandidateImpact(original);
  assert.deepEqual(projected, {
    affected_user_count: 3,
    affected_installation_count: 4,
    affected_toolkit_count: 5,
    affected_agent_count: 6,
    confirmation_actions: ["activate", "reconnect"],
  });
  assert.equal(original.extension, extension);
  assert.deepEqual(original, { ...producerImpact, extension });
});

void test("null and omitted impact keep counters unavailable and actions empty", () => {
  for (const input of [null, void 0, {}]) {
    assert.deepEqual(projectPlatformGitHubCandidateImpact(input), {
      affected_user_count: null,
      affected_installation_count: null,
      affected_toolkit_count: null,
      affected_agent_count: null,
      confirmation_actions: [],
    });
  }
});

void test("known malformed fields preserve the existing display and action filtering semantics", () => {
  for (const invalid of [null, "3", false, [], {}]) {
    assert.equal(
      projectPlatformGitHubCandidateImpact({
        ...producerImpact,
        affected_user_count: invalid,
      }).affected_user_count,
      null,
    );
  }
  assert.deepEqual(
    projectPlatformGitHubCandidateImpact({
      confirmation_actions: ["activate", 4, null, "reconnect"],
    }).confirmation_actions,
    ["activate", "reconnect"],
  );
  for (const invalid of [null, "activate", 4, {}]) {
    assert.deepEqual(
      projectPlatformGitHubCandidateImpact({ confirmation_actions: invalid })
        .confirmation_actions,
      [],
    );
  }
});

void test("numeric observations retain zero and historical number semantics without coercion", () => {
  for (const value of [0, -1, 1.5, Infinity, NaN]) {
    assert.equal(
      projectPlatformGitHubCandidateImpact({ affected_user_count: value })
        .affected_user_count,
      value,
    );
  }
});
