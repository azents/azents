import assert from "node:assert/strict";
import { test } from "node:test";
import * as googleResume from "../../shared/toolkits/google-resume.ts";
import * as googleTypes from "../../shared/toolkits/google-types.ts";
import * as popupMessages from "../../shared/toolkits/popup-messages.ts";
import * as providerConfigViews from "../../shared/toolkits/provider-config-views.ts";
import * as projection from "../../shared/toolkits/toolkit-config-projection.ts";
import * as formLifecycle from "../../shared/toolkits/toolkit-form-lifecycle.ts";
import * as managementState from "../agents/agentToolkitManagementState.ts";
import {
  deferred,
  HookHarness,
  invoke,
  noMutation,
  object,
  ResumeStore,
} from "./google-container-test-harness.ts";
import type { GoogleResume } from "../../shared/toolkits/google-resume.ts";
import type { NativeDeferred } from "./google-container-test-harness.ts";

function receipt(value: NativeDeferred | null): PromiseLike<unknown> {
  if (value == null) {
    throw new Error("The provider receipt must be bound before dispatch.");
  }
  return value.promise;
}

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
    returnPath: googleResume.googleReturnPath("team", "agent", toolkitId),
  };
}
const review = {
  attempt_id: "old",
  reconnect_toolkit_id: null,
  requested_tasks: ["calendar_read"],
  timeout: 30,
  expires_at: deadline,
  tasks: [
    {
      task: "calendar_read",
      service: "calendar",
      status: "partial",
      permitted_tools: ["list_events"],
      unavailable_tools: ["list_calendars"],
    },
  ],
  identity: {
    issuer: "https://accounts.google.com",
    subject: "synthetic",
    email: null,
  },
  client_id: "client",
  ownership: "agent_only",
  renewable: true,
  can_confirm: true,
  grant_result: "partial",
  service_access_verified: false,
  security_notice: "Synthetic notice.",
};

function callbackHarness(
  store: ResumeStore,
  exchange: (input: unknown) => PromiseLike<unknown>,
  cancel: (input: unknown) => PromiseLike<unknown>,
): { harness: HookHarness; routes: unknown[] } {
  const harness = new HookHarness();
  const routes: unknown[] = [];
  const router = { replace: (path: unknown) => routes.push(path) };
  harness.load(
    new URL("./containers/useGoogleCallbackContainer.ts", import.meta.url),
    "useGoogleCallbackContainer",
    {
      react: harness.react,
      "@mantine/hooks": store.mantine,
      "next/navigation": { useRouter: () => router },
      "@/shared/toolkits/google-resume": googleResume,
      "@/trpc/client": {
        trpc: {
          toolkit: {
            google: {
              exchange: { useMutation: () => ({ mutateAsync: exchange }) },
              cancel: { useMutation: () => ({ mutateAsync: cancel }) },
            },
          },
        },
      },
    },
    {
      history: { replaceState: () => {} },
      location: { pathname: "/oauth/google/callback" },
    },
  );
  return { harness, routes };
}
for (const operation of ["exchange", "denial"]) {
  for (const leave of ["unmount", "replacement"]) {
    void test(`actual Google callback fences late ${operation} after ${leave}`, async () => {
      const store = new ResumeStore();
      const old = {
        ...context(),
        phase: "AUTHORIZING",
        stateDigest: await googleResume.googleStateDigest("opaque-state"),
      };
      store.value = old;
      const dispatched = deferred<void>();
      let response: NativeDeferred | null = null;
      const request = (): PromiseLike<unknown> => {
        dispatched.resolve();
        return receipt(response);
      };
      const { harness, routes } = callbackHarness(store, request, request);
      response = harness.nativeDeferred();
      harness.render({
        code: "synthetic-code",
        state: "opaque-state",
        providerError: operation === "denial" ? "access_denied" : null,
      });
      harness.flushEffects();
      await dispatched.promise;
      if (leave === "unmount") {
        harness.unmount();
      }
      const sibling = { ...context("new"), phase: "AUTHORIZING" };
      store.value = sibling;
      const writes = store.writes.length;
      response.resolve(
        operation === "denial"
          ? { cancelled: true, publication: null }
          : review,
      );
      await response.promise;
      assert.equal(object(store.value).attemptId, "new");
      assert.equal(store.writes.length, writes);
      assert.equal(routes.length, 0);
    });
  }
}
void test("actual callback survives Strict Mode probe and dispatches one exact exchange", async () => {
  const store = new ResumeStore();
  store.value = {
    ...context(),
    phase: "AUTHORIZING",
    stateDigest: await googleResume.googleStateDigest("opaque-state"),
  };
  const dispatched = deferred<void>();
  let response: NativeDeferred | null = null;
  let calls = 0;
  const { harness, routes } = callbackHarness(
    store,
    () => {
      calls += 1;
      dispatched.resolve();
      return receipt(response);
    },
    () => Promise.reject(new Error("Unexpected denial.")),
  );
  response = harness.nativeDeferred();
  harness.render({
    code: "synthetic-code",
    state: "opaque-state",
    providerError: null,
  });
  harness.flushEffects();
  harness.probeEffects();
  await dispatched.promise;
  response.resolve(review);
  await response.promise;
  assert.equal(calls, 1);
  assert.equal(object(store.value).phase, "REVIEW");
  assert.deepEqual(routes, [context().returnPath]);
});
void test("denial cancellation observes publication rather than labelling it discarded", async () => {
  const store = new ResumeStore();
  store.value = {
    ...context(),
    phase: "AUTHORIZING",
    stateDigest: await googleResume.googleStateDigest("opaque-state"),
  };
  const dispatched = deferred<void>();
  let response: NativeDeferred | null = null;
  const { harness, routes } = callbackHarness(
    store,
    () => Promise.reject(new Error("Unexpected exchange.")),
    () => {
      dispatched.resolve();
      return receipt(response);
    },
  );
  response = harness.nativeDeferred();
  harness.render({
    code: null,
    state: "opaque-state",
    providerError: "access_denied",
  });
  harness.flushEffects();
  await dispatched.promise;
  response.resolve({
    cancelled: false,
    publication: { toolkit_id: "saved", connection_id: "grant", current: true },
  });
  await response.promise;
  assert.equal(object(store.value).phase, "UNKNOWN");
  assert.deepEqual(routes, [context().returnPath]);
});

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
function managerHarness(store: ResumeStore, items: unknown[]): HookHarness {
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
      "../agents/containers/useAgentToolkitManagementContainer.ts",
      import.meta.url,
    ),
    "useAgentToolkitManagementContainer",
    {
      react: harness.react,
      "@mantine/hooks": store.mantine,
      "next-intl": { useTranslations: translations },
      "@/shared/toolkits/google-resume": googleResume,
      "@/shared/toolkits/toolkit-form-lifecycle": formLifecycle,
      "@/shared/toolkits/github-user-creation-state": {
        creationReturnPath: googleResume.googleReturnPath,
        deserializeGitHubUserCreation: () => null,
        GITHUB_USER_CREATION_KEY: "github.creation",
      },
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
    const store = new ResumeStore();
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
  const store = new ResumeStore();
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
    const store = new ResumeStore();
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

for (const agentOwned of [false, true]) {
  void test(`actual ${agentOwned ? "Agent" : "shared"} metadata save preserves independently confirmed Google configuration`, () => {
    const store = new ResumeStore();
    const harness = new HookHarness();
    const captured: Array<{ route: string; input: unknown }> = [];
    const oldConfig = {
      tasks: ["calendar_read", "calendar_edit"],
      timeout: 30,
      security_risk_acknowledged: true,
    };
    let toolkit = {
      id: "saved",
      toolkit_type: "google",
      name: "Before",
      slug: "google",
      description: null,
      prompt: null,
      config: oldConfig,
      credentials: null,
      enabled: true,
      always_expose_tools: false,
    };
    let values: Record<string, unknown> = {};
    const form = {
      getValues: () => values,
      setValues: (next: unknown) => {
        values = { ...values, ...object(next) };
      },
      setFieldValue: (key: string, value: unknown) => {
        values[key] = value;
      },
      resetDirty: () => {},
      onSubmit: (callback: unknown) => (): void => {
        invoke(callback, values);
      },
    };
    const tk: Record<string, unknown> = {
      listToolkits: {
        useQuery: () => query({ items: [{ slug: "google", name: "Google" }] }),
      },
      getConfig: { useQuery: () => query(toolkit) },
      getAgentConfig: { useQuery: () => query(toolkit) },
    };
    for (const name of [
      "createConfig",
      "updateConfig",
      "createAgentConfig",
      "updateAgentConfig",
      "connectOauth",
      "connectAgentOauth",
      "disconnectOauth",
      "disconnectAgentOauth",
    ]) {
      tk[name] = {
        useMutation: () => ({
          ...noMutation(),
          mutate: (input: unknown) => captured.push({ route: name, input }),
        }),
      };
    }
    const utilsTk: Record<string, unknown> = {};
    for (const name of [
      "getConfig",
      "getAgentConfig",
      "listConfigs",
      "listAgentManagement",
    ]) {
      utilsTk[name] = {
        invalidate: async () => {},
        fetch: () => Promise.resolve({}),
      };
    }
    harness.load(
      new URL(
        "../../shared/toolkits/containers/useToolkitFormContainer.ts",
        import.meta.url,
      ),
      "useToolkitFormContainer",
      {
        react: harness.react,
        "@mantine/hooks": store.mantine,
        "@mantine/form": {
          useForm: (options: unknown) => {
            if (Object.keys(values).length === 0) {
              values = object(object(options).initialValues);
            }
            return form;
          },
        },
        "next-intl": { useTranslations: translations },
        "next/navigation": { useRouter: () => ({ push: () => {} }) },
        "@/trpc/client": {
          trpc: { toolkit: tk, useUtils: () => ({ toolkit: utilsTk }) },
        },
        "@/shared/lib/redacted-credentials": {
          normalizeCredentialEdits: (value: unknown) => value,
        },
        "@/shared/lib/toolkit-identifiers": {
          trimToolkitWhitespace: (value: string) => value.trim(),
          resolveDefaultToolkitSlug: () => "google",
        },
        "@/shared/lib/unknown-value": {
          isRecord: (value: unknown) =>
            value != null && typeof value === "object",
        },
        "../github-user-creation-state": {
          deserializeGitHubUserCreation: () => null,
          GITHUB_USER_CREATION_KEY: "github.creation",
          creationReturnPath: googleResume.googleReturnPath,
        },
        "../github-user-credentials": {
          normalizeGitHubUserCredentialEdits: (value: unknown) => value,
        },
        "../schemas": {
          toolkitFormSchema: { safeParse: () => ({ success: true }) },
        },
        "../toolkit-config-projection": projection,
        "../popup-messages": popupMessages,
        "../provider-config-views": providerConfigViews,
        "../toolkit-form-lifecycle": formLifecycle,
        "../google-resume": googleResume,
      },
      {},
    );
    harness.render({
      handle: "team",
      toolkitId: "saved",
      ...(agentOwned ? { agentId: "agent" } : {}),
    });
    harness.flushEffects();
    harness.render();
    const confirmedConfig = {
      ...oldConfig,
      tasks: ["calendar_read"],
      timeout: 12,
    };
    toolkit = { ...toolkit, config: confirmedConfig };
    let output = harness.render();
    harness.flushEffects();
    invoke(
      object(output.form).setFieldValue,
      "name",
      "Concurrent renamed metadata",
    );
    output = harness.render();
    assert.equal(object(values.config).timeout, 30);
    invoke(output.onSubmit);
    assert.equal(captured.length, 1);
    const sent = captured[0];
    assert.ok(sent);
    assert.equal(sent.route, agentOwned ? "updateAgentConfig" : "updateConfig");
    const patch = object(sent.input);
    assert.equal(Object.hasOwn(patch, "config"), false);
    assert.equal(patch.name, "Concurrent renamed metadata");
    assert.equal(toolkit.config.timeout, 12);
    assert.deepEqual(toolkit.config.tasks, ["calendar_read"]);
  });
}

function setupHarness(
  store: ResumeStore,
  cancelRequest: () => PromiseLike<unknown>,
  reviewRead: () => Promise<unknown>,
  register: (value: unknown) => void,
): HookHarness {
  const harness = new HookHarness();
  const google: Record<string, unknown> = {
    preparation: {
      useQuery: () =>
        query({
          status: "configured_unverified",
          client_id: "client",
          callback_url: "https://app.example.invalid/oauth/google/callback",
          preview_verified: false,
          service_access_verified: false,
        }),
    },
    status: { useQuery: () => query(null) },
  };
  for (const name of [
    "connect",
    "reconnect",
    "confirm",
    "reconnectConfirm",
    "disconnect",
  ]) {
    google[name] = { useMutation: noMutation };
  }
  google.cancel = {
    useMutation: () => ({ ...noMutation(), mutateAsync: cancelRequest }),
  };
  const utilsTk: Record<string, unknown> = {};
  for (const name of [
    "listConfigs",
    "listAvailableConfigs",
    "listAgentManagement",
    "listAgentToolkits",
    "getConfig",
    "getAgentConfig",
  ]) {
    utilsTk[name] = { invalidate: async () => {} };
  }
  utilsTk.google = {
    review: { fetch: reviewRead },
    status: { invalidate: async () => {} },
    outcome: {
      fetch: () => Promise.reject(new Error("Unexpected outcome lookup.")),
    },
  };
  harness.load(
    new URL(
      "../../shared/toolkits/containers/useGoogleSetupContainer.ts",
      import.meta.url,
    ),
    "useGoogleSetupContainer",
    {
      react: harness.react,
      "@mantine/hooks": store.mantine,
      "next-intl": { useTranslations: translations },
      "next/navigation": { useRouter: () => ({ push: () => {} }) },
      "@/trpc/client": {
        trpc: { toolkit: { google }, useUtils: () => ({ toolkit: utilsTk }) },
      },
      "../google-resume": googleResume,
      "../google-types": googleTypes,
      "../github-wizard-progression": { revealGitHubWizardHeading: () => {} },
    },
    {},
  );
  harness.render({
    handle: "team",
    agentId: "agent",
    onAbandonReady: register,
  });
  harness.flushEffects();
  return harness;
}
for (const outcome of ["cancelled", "published", "replaced"]) {
  void test(`exact candidate abandonment ${outcome} preserves browser ownership after unmount`, async () => {
    const store = new ResumeStore();
    store.value = context();
    let abandon: unknown = null;
    const cancelStarted = deferred<void>();
    let cancelled: NativeDeferred | null = null;
    const reviewed = deferred<unknown>();
    const harness = setupHarness(
      store,
      () => {
        cancelStarted.resolve();
        return receipt(cancelled);
      },
      () => reviewed.promise,
      (value) => {
        abandon = value;
      },
    );
    cancelled = harness.nativeDeferred();
    reviewed.resolve(review);
    await reviewed.promise;
    harness.render();
    harness.flushEffects();
    harness.render();
    const handler = abandon;
    invoke(handler);
    await cancelStarted.promise;
    harness.unmount();
    if (outcome === "replaced") {
      store.value = context("new");
    }
    cancelled.resolve({
      cancelled: outcome !== "published",
      publication:
        outcome === "published"
          ? { toolkit_id: "saved", connection_id: "grant", current: true }
          : null,
    });
    await cancelled.promise;
    if (outcome === "cancelled") {
      assert.equal(store.value, null);
    } else if (outcome === "published") {
      assert.equal(object(store.value).attemptId, "old");
      assert.equal(object(store.value).phase, "UNKNOWN");
    } else {
      assert.equal(object(store.value).attemptId, "new");
    }
  });
}
