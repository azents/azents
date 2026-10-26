import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BrowserStorageFixture,
  HookHarness,
  invoke,
  noMutation,
  object,
} from "../../shared/testing/hook-test-harness.ts";
import * as githubCreation from "../../shared/toolkits/github-user-creation-state.ts";
import * as googleResume from "../../shared/toolkits/google-resume.ts";
import * as providerConfigViews from "../../shared/toolkits/provider-config-views.ts";
import * as formLifecycle from "../../shared/toolkits/toolkit-form-lifecycle.ts";
import * as managementState from "./agentToolkitManagementState.ts";
import type { GoogleResume } from "../../shared/toolkits/google-resume.ts";

const deadline = "2030-01-01T00:00:00Z";
function context(attemptId = "old", toolkitId?: string): GoogleResume {
  return {
    handle: "team",
    agentId: "agent",
    attemptId,
    toolkitId,
    expiresAt: deadline,
    stateDigest: "a".repeat(64),
    phase: "REVIEW",
    returnPath: googleResume.googleReturnPath(
      { handle: "team", agentId: "agent" },
      toolkitId,
    ),
  };
}
function query(data: unknown): Record<string, unknown> {
  return {
    data,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
  };
}
function translations(): (key: string) => string {
  return (key) => key;
}
function managerHarness(
  store: BrowserStorageFixture,
  items: unknown[],
): HookHarness {
  const harness = new HookHarness();
  const toolkit: Record<string, unknown> = {
    listAgentManagement: {
      useQuery: () => query({ items, available_shared: [] }),
    },
    listToolkits: {
      useQuery: () => query({ items: [{ slug: "google", name: "Google" }] }),
    },
  };
  for (const name of [
    "attachToAgent",
    "detachFromAgent",
    "updateAgentConfig",
    "removeAgentConfig",
    "connectOauth",
    "connectAgentOauth",
  ]) {
    toolkit[name] = { useMutation: noMutation };
  }
  const utils = {
    toolkit: {
      listAgentManagement: { invalidate: async () => {} },
      githubUser: {
        status: { invalidate: async () => {} },
        access: { invalidate: async () => {} },
        review: { invalidate: async () => {} },
      },
      getAgentConfig: { invalidate: async () => {} },
    },
  };
  harness.load(
    new URL(
      "./containers/useAgentToolkitManagementContainer.ts",
      import.meta.url,
    ),
    "useAgentToolkitManagementContainer",
    {
      react: harness.react,
      "@/shared/agent-session/useAgentLifecycle": {
        useAgentLifecycle: () => ({ readOnly: false }),
      },
      "@mantine/hooks": store.mantine,
      "next-intl": { useTranslations: translations },
      "@/shared/toolkits/google-resume": googleResume,
      "@/shared/toolkits/toolkit-form-lifecycle": formLifecycle,
      "@/shared/toolkits/provider-config-views": providerConfigViews,
      "@/shared/toolkits/github-user-creation-state": githubCreation,
      "@/shared/toolkits/github-user-oauth-state": {
        deserializeGitHubUserContext: () => null,
        GITHUB_USER_CONTEXT_KEY: "github.context",
      },
      "../agentToolkitManagementState": managementState,
      "@/trpc/client": {
        trpc: {
          toolkit,
          useUtils: () => utils,
          workspaceMember: { me: { useQuery: () => query({ role: "owner" }) } },
        },
      },
    },
    { location: { origin: "https://app.example.invalid" } },
  );
  return harness;
}
void test("actual Agent management restores Google create and uncertain publication", () => {
  for (const phase of ["REVIEW", "VERIFYING", "UNKNOWN", "PUBLISHING"]) {
    const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
    store.value = { ...context(), phase };
    const harness = managerHarness(store, []);
    harness.render({ handle: "team", agentId: "agent" });
    harness.flushEffects();
    const editor = object(harness.render().editor);
    assert.equal(editor.type, "CREATE");
    assert.equal(editor.toolkitType, "google");
  }
});
void test("actual Agent management restores only the exact owned Google reconnect editor", () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  store.value = context("old", "saved");
  const item = {
    ownership_scope: "agent_only",
    toolkit: { id: "saved", toolkit_type: "google" },
  };
  const harness = managerHarness(store, [item]);
  harness.render({ handle: "team", agentId: "agent" });
  harness.flushEffects();
  assert.equal(object(harness.render().editor).toolkitConfigId, "saved");
  for (const invalid of [{ handle: "other" }, { agentId: "other" }]) {
    const wrong = managerHarness(store, [item]);
    wrong.render({ handle: "team", agentId: "agent", ...invalid });
    wrong.flushEffects();
    assert.equal(object(wrong.render().editor).type, "CLOSED");
  }
  const shared = managerHarness(store, [
    { ...item, ownership_scope: "workspace_shared" },
  ]);
  shared.render({ handle: "team", agentId: "agent" });
  shared.flushEffects();
  assert.equal(object(shared.render().editor).type, "CLOSED");
});
for (const action of ["close", "back"]) {
  void test(`actual Agent Google ${action} invokes exact abandonment and guards unknown publication`, () => {
    const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
    store.value = context();
    const harness = managerHarness(store, []);
    harness.render({ handle: "team", agentId: "agent" });
    harness.flushEffects();
    let output = harness.render();
    let abandoned = 0;
    invoke(output.onCreateAbandonReady, () => {
      abandoned += 1;
    });
    invoke(output.onCreatePublicationPendingChange, true);
    output = harness.render();
    invoke(
      action === "close" ? output.onCloseEditor : output.onCatalogTabChange,
      "new",
    );
    assert.equal(abandoned, 0);
    assert.equal(object(harness.render().editor).type, "CREATE");
    invoke(output.onCreatePublicationPendingChange, false);
    output = harness.render();
    invoke(
      action === "close" ? output.onCloseEditor : output.onCatalogTabChange,
      "new",
    );
    assert.equal(abandoned, 1);
    assert.equal(
      object(harness.render().editor).type,
      action === "close" ? "CLOSED" : "CATALOG",
    );
  });
}
for (const action of ["close", "back"]) {
  void test(`actual Agent GitHub ${action} invokes registered abandonment only after publication settles`, () => {
    const store = new BrowserStorageFixture(
      githubCreation.GITHUB_USER_CREATION_KEY,
    );
    store.value = {
      handle: "team",
      agentId: "agent",
      attemptId: "reviewed-github",
      phase: "REVIEW",
      returnPath: githubCreation.creationReturnPath({
        handle: "team",
        agentId: "agent",
      }),
    };
    const harness = managerHarness(store, []);
    harness.render({ handle: "team", agentId: "agent" });
    harness.flushEffects();
    let output = harness.render();
    assert.equal(object(output.editor).toolkitType, "github");
    let abandoned = 0;
    invoke(output.onCreateAbandonReady, () => {
      abandoned += 1;
    });
    invoke(output.onCreatePublicationPendingChange, true);
    output = harness.render();
    invoke(
      action === "close" ? output.onCloseEditor : output.onCatalogTabChange,
      "new",
    );
    assert.equal(abandoned, 0);
    assert.equal(object(harness.render().editor).type, "CREATE");
    invoke(output.onCreatePublicationPendingChange, false);
    output = harness.render();
    invoke(
      action === "close" ? output.onCloseEditor : output.onCatalogTabChange,
      "new",
    );
    assert.equal(abandoned, 1);
    assert.equal(
      object(harness.render().editor).type,
      action === "close" ? "CLOSED" : "CATALOG",
    );
  });
}
