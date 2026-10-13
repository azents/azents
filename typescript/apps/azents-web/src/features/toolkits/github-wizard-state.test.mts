import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { z } from "zod/v4";
import {
  acceptGitHubCreationResult,
  GitHubWizardOperations,
} from "../../shared/toolkits/github-wizard-operations.ts";
import {
  DEFAULT_GITHUB_WIZARD_SETTINGS,
  finalWizardSettings,
  GITHUB_FEATURE_GROUPS,
  isWizardMode,
  wizardCandidateRequiresRestart,
  wizardIdentity,
  wizardMode,
} from "../../shared/toolkits/github-wizard-state.ts";

void test("identity maps to the five retained auth modes without offering App PAT", () => {
  assert.equal(wizardMode("PERSONAL", "PAT"), "pat");
  assert.equal(wizardMode("PERSONAL", "PLATFORM"), "github_app_platform_user");
  assert.equal(wizardMode("PERSONAL", "SELF_MANAGED"), "github_app_user");
  assert.equal(wizardMode("APP", "PAT"), null);
  assert.equal(wizardMode("APP", "PLATFORM"), "github_app_platform");
  assert.equal(wizardMode("APP", "SELF_MANAGED"), "github_app");
  assert.equal(wizardIdentity("github_app_platform_user"), "PERSONAL");
  assert.equal(wizardIdentity("github_app"), "APP");
  assert.equal(isWizardMode("made-up-mode"), false);
});

void test("final settings are complete, normalize default identifiers and exclude auth authority", () => {
  const result = finalWizardSettings({
    ...DEFAULT_GITHUB_WIZARD_SETTINGS,
    name: "\u0085",
    slug: "\u0085",
    toolsets: [...GITHUB_FEATURE_GROUPS, "future_supported_group"],
    timeout: 42,
    injectRuntimeEnvironment: true,
    runtimeRiskAcknowledged: true,
  });
  assert.deepEqual(
    Object.keys(result).sort(),
    [
      "name",
      "slug",
      "description",
      "prompt",
      "enabled",
      "always_expose_tools",
      "toolsets",
      "timeout",
      "inject_runtime_environment",
      "runtime_risk_acknowledged",
    ].sort(),
  );
  assert.equal(result.name, null);
  assert.equal(result.slug, null);
  assert.equal(result.timeout, 42);
  assert.equal(result.inject_runtime_environment, true);
  assert.equal(result.runtime_risk_acknowledged, true);
  assert.equal(result.toolsets.length, 11);
  assert.equal(DEFAULT_GITHUB_WIZARD_SETTINGS.injectRuntimeEnvironment, false);
});

void test("post-authorization edits, not pre-authentication defaults, form the final command", () => {
  const reviewed = {
    ...DEFAULT_GITHUB_WIZARD_SETTINGS,
    name: "Reviewed name",
    slug: "reviewed-name",
    description: "New description",
    prompt: "New prompt",
    enabled: false,
    alwaysExposeTools: true,
    toolsets: ["actions", "notifications"],
    timeout: 21,
  };
  const result = finalWizardSettings(reviewed);
  assert.equal(result.name, "Reviewed name");
  assert.equal(result.slug, "reviewed-name");
  assert.equal(result.description, "New description");
  assert.equal(result.prompt, "New prompt");
  assert.equal(result.enabled, false);
  assert.equal(result.always_expose_tools, true);
  assert.deepEqual(result.toolsets, ["actions", "notifications"]);
});

void test("abandonment rejects a deferred connect result and cancels only that returned attempt", async () => {
  const operations = new GitHubWizardOperations();
  const operation = operations.next();
  const result = Promise.withResolvers<string>();
  const canceled: string[] = [];
  let navigated = false;
  const continuation = result.promise.then((attemptId) => {
    if (
      acceptGitHubCreationResult(
        operations.isCurrent(operation),
        attemptId,
        (id) => canceled.push(id),
      )
    ) {
      navigated = true;
    }
  });
  operations.next();
  result.resolve("late-exact-attempt");
  await continuation;
  assert.deepEqual(canceled, ["late-exact-attempt"]);
  assert.equal(navigated, false);
});

void test("changing mode rejects an older successful verification even after returning to the same mode", () => {
  const operations = new GitHubWizardOperations();
  const firstPat = operations.next();
  operations.next();
  const secondPat = operations.next();
  assert.equal(operations.isCurrent(firstPat), false);
  assert.equal(operations.isCurrent(secondPat), true);
});

void test("a current connect result is accepted without canceling intentional OAuth navigation", () => {
  const operations = new GitHubWizardOperations();
  const current = operations.next();
  const canceled: string[] = [];
  assert.equal(
    acceptGitHubCreationResult(
      operations.isCurrent(current),
      "live-attempt",
      (id) => canceled.push(id),
    ),
    true,
  );
  assert.deepEqual(canceled, []);
});

void test("Korean identity copy stays natural while fixed registration and reset actions remain exact", () => {
  const messages = z
    .object({
      toolkits: z.object({
        github: z.object({
          wizard: z.object({
            identityTitle: z.string(),
            personalChoice: z.string(),
            personalDescription: z.string(),
            appChoice: z.string(),
            appDescription: z.string(),
            methodTitle: z.string(),
            selfManagedMethod: z.string(),
            reset: z.string(),
          }),
        }),
      }),
    })
    .parse(
      JSON.parse(
        readFileSync(
          new URL("../../../messages/ko-KR/workspace.json", import.meta.url),
          "utf8",
        ),
      ),
    );
  assert.deepEqual(messages.toolkits.github.wizard, {
    identityTitle: "어떤 계정으로 GitHub에 연결할까요?",
    personalChoice: "내 GitHub 계정으로 연결",
    personalDescription: "내 계정으로 GitHub 작업을 처리합니다.",
    appChoice: "GitHub App으로 연결",
    appDescription: "개인 계정 대신 GitHub App으로 작업합니다.",
    methodTitle: "연결 방법을 선택하세요",
    selfManagedMethod: "새로운 GitHub App 등록",
    reset: "연결 다시 설정",
  });
});

void test("expired or denied exact candidate metadata requires restart; provider transport failures retain retry", () => {
  for (const code of ["CONFLICT", "NOT_FOUND", "FORBIDDEN", "UNAUTHORIZED"]) {
    assert.equal(wizardCandidateRequiresRestart({ data: { code } }), true);
  }
  assert.equal(
    wizardCandidateRequiresRestart({ data: { code: "INTERNAL_SERVER_ERROR" } }),
    false,
  );
  assert.equal(
    wizardCandidateRequiresRestart(new Error("Provider metadata unavailable")),
    false,
  );
});
