import assert from "node:assert/strict";
import { test } from "node:test";
import { skipToken } from "@tanstack/react-query";
import {
  BrowserStorageFixture,
  deferred,
  HookHarness,
  invoke,
  noMutation,
  object,
} from "../../shared/testing/hook-test-harness.ts";
import * as googleAccess from "../../shared/toolkits/google-access.ts";
import * as googleEditor from "../../shared/toolkits/google-editor.ts";
import {
  googleFixtureScopes,
  googleGroupCatalog,
} from "../../shared/toolkits/google-group-fixtures.ts";
import * as googleResume from "../../shared/toolkits/google-resume.ts";
import * as googleTypes from "../../shared/toolkits/google-types.ts";
import * as popupMessages from "../../shared/toolkits/popup-messages.ts";
import * as providerConfigViews from "../../shared/toolkits/provider-config-views.ts";
import * as projection from "../../shared/toolkits/toolkit-config-projection.ts";
import * as formLifecycle from "../../shared/toolkits/toolkit-form-lifecycle.ts";
import type { NativeDeferred } from "../../shared/testing/hook-test-harness.ts";
import type { GoogleResume } from "../../shared/toolkits/google-resume.ts";

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
    returnPath: googleResume.googleReturnPath(
      { handle: "team", agentId: "agent" },
      toolkitId,
    ),
  };
}
const review = {
  attempt_id: "old",
  reconnect_toolkit_id: null,
  services: ["calendar"],
  tool_groups: ["calendar_read"],
  oauth_request_scopes: googleFixtureScopes(["calendar"]),
  granted_scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"],
  drive_access: {
    whole_content_read: false,
    whole_content_write: false,
    whole_metadata_read: false,
    whole_metadata_write: false,
    app_file_read: false,
    app_file_write: false,
  },
  timeout: 30,
  expires_at: deadline,
  accesses: [
    {
      service: "calendar",
      enabled: true,
      status: "partial",
      permitted_tools: ["calendar_list_events"],
      unavailable_tools: ["calendar_list_calendars"],
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
};

function callbackHarness(
  store: BrowserStorageFixture,
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
      const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
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
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
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
void test("actual personal Google callback exchanges with a required Workspace handle and returns to Workspace personal management", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  const personal: GoogleResume = {
    owner: "user",
    handle: "workspace",
    toolkitId: "saved",
    attemptId: "personal",
    expiresAt: deadline,
    stateDigest: await googleResume.googleStateDigest("opaque-personal-state"),
    phase: "AUTHORIZING",
    returnPath: googleResume.googleReturnPath(
      { owner: "user", handle: "workspace" },
      "saved",
    ),
  };
  store.value = personal;
  let input: unknown = null;
  const dispatched = deferred<void>();
  let response: NativeDeferred | null = null;
  const { harness, routes } = callbackHarness(
    store,
    (value) => {
      input = value;
      dispatched.resolve();
      return receipt(response);
    },
    () => Promise.reject(new Error("Unexpected cancellation.")),
  );
  response = harness.nativeDeferred();
  harness.render({
    code: "fixture-code",
    state: "opaque-personal-state",
    providerError: null,
  });
  harness.flushEffects();
  await dispatched.promise;
  assert.equal(object(input).owner, "user");
  assert.equal(object(input).handle, "workspace");
  assert.equal(Object.hasOwn(object(input), "agentId"), false);
  response.resolve({
    ...review,
    attempt_id: "personal",
    ownership: "personal",
    reconnect_toolkit_id: "saved",
  });
  await response.promise;
  assert.equal(object(store.value).phase, "REVIEW");
  assert.deepEqual(routes, [personal.returnPath]);
});
void test("denial cancellation observes publication rather than labelling it discarded", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
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
for (const agentOwned of [false, true]) {
  void test(`actual ${agentOwned ? "Agent" : "shared"} metadata save preserves independently confirmed Google configuration`, () => {
    const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
    const harness = new HookHarness();
    const captured: Array<{ route: string; input: unknown }> = [];
    const oldConfig = {
      services: ["calendar"],
      oauth_request_scopes: [
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events",
      ],
      timeout: 30,
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
          mutateAsync: (input: unknown): Promise<unknown> => {
            captured.push({ route: name, input });
            return Promise.resolve(toolkit);
          },
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
    const personal = {
      get: { useQuery: () => query(null) },
      create: { useMutation: noMutation },
      update: { useMutation: noMutation },
      connectOauth: { useMutation: noMutation },
      disconnectOauth: { useMutation: noMutation },
    };
    const api = {
      toolkit: tk,
      personalToolkit: personal,
      useUtils: () => ({ toolkit: utilsTk }),
    };
    const ownerAdapter = harness.load(
      new URL(
        "../../shared/toolkits/containers/useToolkitOwnerAdapter.ts",
        import.meta.url,
      ),
      "useToolkitOwnerAdapter",
      {
        "@tanstack/react-query": { skipToken },
        "@/trpc/client": { trpc: api },
        "@/shared/lib/toolkit-identifiers": {
          trimToolkitWhitespace: (value: string): string => value.trim(),
        },
        "../toolkit-form-lifecycle": formLifecycle,
      },
      {},
    );
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
          trpc: api,
        },
        "./useToolkitOwnerAdapter": { useToolkitOwnerAdapter: ownerAdapter },
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
      services: ["calendar"],
      oauth_request_scopes: googleFixtureScopes(["calendar"]),
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
    assert.deepEqual(toolkit.config.services, ["calendar"]);
  });
}

function setupHarness(
  store: BrowserStorageFixture,
  cancelRequest: () => PromiseLike<unknown>,
  reviewRead: () => Promise<unknown>,
  register: (value: unknown) => void,
  management: {
    status: () => unknown;
    save: (input: unknown) => Promise<unknown>;
  } | null,
  authorizeRequest?: ((input: unknown) => PromiseLike<unknown>) | null,
  confirmRequest?: (input: unknown) => PromiseLike<unknown>,
  editor?: {
    draft?: googleEditor.GoogleEditorDraft;
    props?: Record<string, unknown>;
    draftStore?: BrowserStorageFixture;
    outcome?: () => Promise<unknown>;
    statusQuery?: () => Record<string, unknown>;
    invalidate?: () => Promise<void>;
  },
): HookHarness {
  const harness = new HookHarness();
  const draftStore =
    editor?.draftStore ??
    new BrowserStorageFixture(googleEditor.GOOGLE_DRAFT_KEY);
  if (editor?.draft != null) {
    draftStore.value = editor.draft;
  }
  const storage = {
    ...store.mantine,
    readSessionStorageValue: (options: unknown): unknown =>
      object(options).key === googleEditor.GOOGLE_DRAFT_KEY
        ? draftStore.mantine.readSessionStorageValue(options)
        : store.mantine.readSessionStorageValue(options),
    useSessionStorage: (
      options: unknown,
    ): ReturnType<typeof store.mantine.useSessionStorage> =>
      object(options).key === googleEditor.GOOGLE_DRAFT_KEY
        ? draftStore.mantine.useSessionStorage()
        : store.mantine.useSessionStorage(),
  };
  const google: Record<string, unknown> = {
    preparation: {
      useQuery: () =>
        query({
          status: "configured_unverified",
          client_id: "client",
          tool_group_catalog: googleGroupCatalog,
          callback_url: "https://app.example.invalid/oauth/google/callback",
          picker_status: "not_configured",
          service_access_verified: false,
        }),
    },
    status: {
      useQuery: () =>
        editor?.statusQuery?.() ?? query(management?.status() ?? null),
    },
  };
  for (const name of [
    "connect",
    "reconnect",
    "confirm",
    "reconnectConfirm",
    "disconnect",
    "services",
    "pickerToken",
  ]) {
    google[name] = { useMutation: noMutation };
  }
  google.cancel = {
    useMutation: () => ({ ...noMutation(), mutateAsync: cancelRequest }),
  };
  if (authorizeRequest != null) {
    for (const name of ["connect", "reconnect"]) {
      google[name] = {
        useMutation: () => ({ ...noMutation(), mutateAsync: authorizeRequest }),
      };
    }
  }
  if (confirmRequest != null) {
    for (const name of ["confirm", "reconnectConfirm"]) {
      google[name] = {
        useMutation: () => ({ ...noMutation(), mutateAsync: confirmRequest }),
      };
    }
  }
  if (management != null) {
    google.services = {
      useMutation: () => ({ ...noMutation(), mutateAsync: management.save }),
    };
  }
  const utilsTk: Record<string, unknown> = {};
  for (const name of [
    "listConfigs",
    "listAvailableConfigs",
    "listAgentManagement",
    "listAgentToolkits",
    "getConfig",
    "getAgentConfig",
  ]) {
    utilsTk[name] = { invalidate: editor?.invalidate ?? (async () => {}) };
  }
  utilsTk.google = {
    review: { fetch: reviewRead },
    status: {
      invalidate: async () => {},
      fetch: () => Promise.resolve(management?.status()),
    },
    outcome: {
      fetch:
        editor?.outcome ??
        (() => Promise.reject(new Error("Unexpected outcome lookup."))),
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
      "@mantine/hooks": storage,
      "next-intl": { useTranslations: translations },
      "next/navigation": { useRouter: () => ({ push: () => {} }) },
      "@/trpc/client": {
        trpc: { toolkit: { google }, useUtils: () => ({ toolkit: utilsTk }) },
      },
      "../google-resume": googleResume,
      "../google-types": googleTypes,
      "../google-editor": googleEditor,
      "../google-access": googleAccess,
      "./useGooglePickerContainer": {
        useGooglePickerContainer: () => ({
          picker: { type: "IDLE" },
          onOpenPicker: () => {},
          onClosePicker: () => {},
        }),
      },
      "../github-wizard-progression": { revealGitHubWizardHeading: () => {} },
    },
    {},
  );
  harness.render({
    handle: "team",
    agentId: "agent",
    onAbandonReady: register,
    ...(management != null ? { toolkitId: "saved" } : {}),
    ...editor?.props,
  });
  harness.flushEffects();
  harness.render();
  harness.flushEffects();
  return harness;
}
for (const outcome of ["cancelled", "published", "replaced"]) {
  void test(`exact candidate abandonment ${outcome} preserves browser ownership after unmount`, async () => {
    const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
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
      null,
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

void test("saved service switches allow all-off without replacing scope intent or grant", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  const calls: unknown[] = [];
  let current = {
    toolkit_id: "saved",
    revision: 7,
    connection_id: "same-grant",
    status: "connected",
    identity: review.identity,
    services: ["calendar"],
    tool_groups: review.tool_groups,
    oauth_request_scopes: review.oauth_request_scopes,
    granted_scopes: review.granted_scopes,
    accesses: review.accesses,
    drive_access: review.drive_access,
    renewable: true,
    timeout: 30,
    service_access_verified: false,
  };
  const harness = setupHarness(
    store,
    () => Promise.reject(new Error("Unexpected cancellation.")),
    () => Promise.resolve(review),
    () => {},
    {
      status: () => current,
      save: (input) => {
        calls.push(input);
        current = { ...current, revision: 8, services: [] };
        return Promise.resolve(current);
      },
    },
  );
  let output = harness.render();
  invoke(output.onServiceChange, "calendar", false);
  output = harness.render();
  assert.equal(output.servicesDirty, true);
  assert.equal(JSON.stringify(output.services), "[]");
  await invoke(output.onSaveServices);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    {
      handle: "team",
      agentId: "agent",
      toolkitId: "saved",
      expectedRevision: 7,
      services: [],
      toolGroups: review.tool_groups,
      timeout: 30,
    },
  ]);
  output = harness.render();
  assert.equal(object(object(output.saved).detail).connection_id, "same-grant");
  assert.deepEqual(current.oauth_request_scopes, review.oauth_request_scopes);
  assert.deepEqual(current.granted_scopes, review.granted_scopes);
  assert.equal(output.savingServices, false);
  assert.equal(output.servicesDirty, false);
});

for (const ownership of ["workspace", "agent", "user"]) {
  void test(`${ownership} consent requests the selected preset's permissions`, async () => {
    const dispatched = deferred<unknown>();
    const h = setupHarness(
      new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY),
      () => Promise.reject(new Error("Unexpected cancellation.")),
      () => Promise.resolve(review),
      () => {},
      null,
      (input) => {
        dispatched.resolve(input);
        return Promise.reject(
          new Error("Synthetic stop before Google navigation."),
        );
      },
    );
    let output = h.render({
      handle: "team",
      ...(ownership === "agent" ? { agentId: "agent" } : {}),
      ...(ownership === "user" ? { owner: "user" } : {}),
    });
    h.flushEffects();
    invoke(output.onServiceChange, "drive", true);
    output = h.render();
    invoke(output.onServiceChange, "gmail", true);
    output = h.render();
    invoke(output.onServiceChange, "gmail", false);
    output = h.render();
    invoke(output.onPresetChange, "drive", "read_only");
    output = h.render();
    invoke(output.onAuthorize);
    const input = object(await dispatched.promise);
    assert.deepEqual(JSON.parse(JSON.stringify(object(input.desired))), {
      services: ["drive"],
      tool_groups: ["drive_read"],
      oauth_request_scopes: googleAccess.googleScopesForGroups(
        ["drive_read"],
        googleGroupCatalog,
      ),
      timeout: 30,
    });
    assert.equal(input.owner ?? null, ownership === "user" ? "user" : null);
    assert.equal(input.agentId ?? null, ownership === "agent" ? "agent" : null);
  });
}

void test("explicit reconnect offers supported permissions without changing saved grant evidence", async () => {
  const dispatched = deferred<unknown>();
  const saved = {
    ...review,
    toolkit_id: "saved",
    revision: 7,
    status: "connected",
    connection_id: "same-grant",
  };
  const h = setupHarness(
    new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY),
    () => Promise.reject(new Error("Unexpected cancellation.")),
    () => Promise.resolve(review),
    () => {},
    {
      status: () => saved,
      save: () => Promise.reject(new Error("Unexpected service save.")),
    },
    (input) => {
      dispatched.resolve(input);
      return Promise.reject(
        new Error("Synthetic stop before Google navigation."),
      );
    },
  );
  const output = h.render();
  invoke(output.onAuthorize);
  const input = object(await dispatched.promise);
  assert.equal(input.toolkitId, "saved");
  assert.deepEqual(
    JSON.parse(JSON.stringify(object(input.desired).oauth_request_scopes)),
    googleAccess.googleScopesForGroups(["calendar_read"], googleGroupCatalog),
  );
  assert.deepEqual(saved.granted_scopes, review.granted_scopes);
  assert.equal(saved.connection_id, "same-grant");
});

void test("partial consent remains uncommitted until the user reauthenticates", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  store.value = context();
  const reviewed = deferred<unknown>();
  let publications = 0;
  const narrow = {
    ...review,
    oauth_request_scopes: [
      "email",
      "https://www.googleapis.com/auth/calendar.events.readonly",
      "openid",
    ],
  };
  const h = setupHarness(
    store,
    () => Promise.reject(new Error("Unexpected cancellation.")),
    () => reviewed.promise,
    () => {},
    null,
    null,
    () => {
      publications += 1;
      return Promise.reject(new Error("Synthetic unconfirmed publication."));
    },
  );
  reviewed.resolve(narrow);
  await reviewed.promise;
  const output = h.render();
  h.flushEffects();
  assert.equal(object(output.flow).type, "REVIEW");
  assert.equal(output.reviewDecision, "PARTIAL");
  assert.equal(publications, 0);
  assert.deepEqual(narrow.granted_scopes, review.granted_scopes);
});

for (const purpose of ["CONNECT", "RECOVER", "APPLY"] as const) {
  void test(`normal ${purpose} automatically confirms once without a second save`, async () => {
    const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
    const toolkitId = purpose === "CONNECT" ? void 0 : "saved";
    store.value = { ...context("old", toolkitId), purpose };
    const full = {
      ...review,
      reconnect_toolkit_id: toolkitId ?? null,
      accesses: [
        {
          ...review.accesses[0],
          permitted_tools:
            googleGroupCatalog.find((group) => group.group === "calendar_read")
              ?.operations ?? [],
        },
      ],
    };
    const saved = {
      ...full,
      toolkit_id: "saved",
      revision: 7,
      connection_id: "old-connection",
      status: "connected",
    };
    const observed = deferred<unknown>();
    const published = deferred<unknown>();
    const draft: googleEditor.GoogleEditorDraft = {
      handle: "team",
      agentId: "agent",
      toolkitId,
      attemptId: "old",
      expiresAt: deadline,
      metadata: {
        ...googleEditor.emptyGoogleMetadata,
        name: "Unapplied name",
        slug: "google",
      },
      services: ["calendar"],
      toolGroups: ["calendar_read"],
      timeout: 30,
      revision: toolkitId == null ? null : 7,
      baseline:
        toolkitId == null
          ? null
          : {
              services: ["calendar"],
              toolGroups: ["calendar_read"],
              timeout: 30,
            },
    };
    const calls: unknown[] = [];
    const h = setupHarness(
      store,
      () => Promise.reject(new Error("Unexpected cancellation")),
      () => {
        observed.resolve(full);
        return observed.promise;
      },
      () => {},
      toolkitId == null
        ? null
        : {
            status: () => saved,
            save: () => Promise.reject(new Error("No second save")),
          },
      null,
      (input) => {
        calls.push(input);
        published.resolve(input);
        return Promise.reject(new Error("Synthetic uncertain publication"));
      },
      { draft },
    );
    await observed.promise;
    h.render();
    h.flushEffects();
    const input = object(await published.promise);
    assert.equal(calls.length, 1);
    const settings = object(input.settings);
    assert.equal(Object.hasOwn(settings, "metadata"), purpose === "APPLY");
    if (purpose === "APPLY") {
      assert.equal(object(settings.metadata).name, "Unapplied name");
    }
    if (purpose === "CONNECT") {
      assert.equal(settings.name, "Unapplied name");
    }
    h.render();
    h.flushEffects();
    assert.equal(calls.length, 1);
  });
}

void test("changed principal does not auto-confirm even when every capability is granted", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  store.value = { ...context("old", "saved"), purpose: "RECOVER" };
  const observed = deferred<unknown>();
  const full = {
    ...review,
    reconnect_toolkit_id: "saved",
    identity: { ...review.identity, subject: "different" },
    accesses: [
      {
        ...review.accesses[0],
        permitted_tools:
          googleGroupCatalog.find((group) => group.group === "calendar_read")
            ?.operations ?? [],
      },
    ],
  };
  const calls: unknown[] = [];
  const h = setupHarness(
    store,
    () => Promise.resolve({ publication: null }),
    () => {
      observed.resolve(full);
      return observed.promise;
    },
    () => {},
    {
      status: () => ({
        ...review,
        toolkit_id: "saved",
        revision: 7,
        connection_id: "connection",
        status: "connected",
      }),
      save: () => Promise.reject(new Error("No settings save")),
    },
    null,
    (input) => {
      calls.push(input);
      return Promise.resolve(null);
    },
  );
  await observed.promise;
  const output = h.render();
  h.flushEffects();
  assert.equal(output.reviewDecision, "ACCOUNT");
  assert.equal(calls.length, 0);
});

for (const current of [true, false]) {
  void test(`uncertain APPLY adopts only its canonical current=${current} outcome without another save`, async () => {
    const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
    store.value = {
      ...context("old", "saved"),
      phase: "UNKNOWN",
      purpose: "APPLY",
    };
    const draftStore = new BrowserStorageFixture(googleEditor.GOOGLE_DRAFT_KEY);
    const draft: googleEditor.GoogleEditorDraft = {
      handle: "team",
      agentId: "agent",
      toolkitId: "saved",
      attemptId: "old",
      expiresAt: deadline,
      metadata: {
        ...googleEditor.emptyGoogleMetadata,
        name: "Edited",
        slug: "google",
      },
      services: ["calendar", "gmail"],
      toolGroups: ["calendar_read", "gmail_read"],
      timeout: 12,
      revision: 7,
      baseline: {
        services: ["calendar", "gmail"],
        toolGroups: ["calendar_read", "gmail_read"],
        timeout: 30,
      },
    };
    const published = {
      ...review,
      toolkit_id: "saved",
      revision: 8,
      connection_id: "new-grant",
      status: "connected",
      services: ["calendar"],
      tool_groups: ["calendar_read"],
      timeout: 12,
      granted_tools: review.accesses.flatMap(
        (access) => access.permitted_tools,
      ),
    };
    let writes = 0;
    const h = setupHarness(
      store,
      () => Promise.reject(new Error("No cancellation")),
      () => Promise.reject(new Error("No review replay")),
      () => {},
      {
        status: () => published,
        save: () => {
          writes++;
          return Promise.reject(new Error("No second save"));
        },
      },
      null,
      () => {
        writes++;
        return Promise.reject(new Error("No confirmation replay"));
      },
      {
        draft,
        draftStore,
        outcome: () =>
          Promise.resolve({
            toolkit_id: "saved",
            connection_id: "new-grant",
            current,
          }),
        props: {
          initialMetadata: {
            ...googleEditor.emptyGoogleMetadata,
            name: "Original",
            slug: "google",
          },
        },
      },
    );
    const output = h.render();
    h.flushEffects();
    await invoke(output.onCheckOutcome);
    const settled = h.render();
    assert.equal(object(settled.flow).type, "COMPLETE");
    assert.equal(writes, 0);
    if (current) {
      assert.equal(settled.settingsDirty, false);
      assert.deepEqual(JSON.parse(JSON.stringify(settled.services)), [
        "calendar",
      ]);
      assert.equal(draftStore.value, null);
    } else {
      assert.equal(settled.settingsDirty, true);
      assert.notEqual(draftStore.value, null);
    }
  });
}

void test("a successful status reload hydrates the editor after its first read failed", () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  let failed = true;
  const status = {
    ...review,
    toolkit_id: "saved",
    revision: 7,
    connection_id: "grant",
    status: "connected",
    timeout: 12,
    granted_tools: [],
  };
  const h = setupHarness(
    store,
    () => Promise.reject(new Error("No cancel")),
    () => Promise.reject(new Error("No review")),
    () => {},
    { status: () => status, save: () => Promise.reject(new Error("No save")) },
    null,
    void 0,
    {
      statusQuery: () =>
        failed ? { ...query(null), isError: true } : query(status),
    },
  );
  assert.equal(object(h.render().saved).type, "ERROR");
  failed = false;
  h.render();
  h.flushEffects();
  const loaded = h.render();
  assert.equal(loaded.timeout, 12);
  assert.deepEqual(JSON.parse(JSON.stringify(loaded.services)), ["calendar"]);
  assert.equal(loaded.settingsDirty, false);
});

void test("status refetch and Strict Mode preserve a dirty draft and its original revision", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  let status = {
    ...review,
    toolkit_id: "saved",
    revision: 7,
    connection_id: "grant",
    status: "connected",
    granted_tools: [],
  };
  let applied: unknown = null;
  const h = setupHarness(
    store,
    () => Promise.reject(new Error("No cancel")),
    () => Promise.reject(new Error("No review")),
    () => {},
    {
      status: () => status,
      save: (input) => {
        applied = input;
        return Promise.reject(new Error("Revision conflict"));
      },
    },
  );
  invoke(h.render().onServiceChange, "calendar", false);
  invoke(h.render().onGroupChange, "calendar_read", false);
  invoke(h.render().onTimeoutChange, 12);
  invoke(h.render().onMetadataChange, { name: "Unapplied" });
  h.render();
  h.flushEffects();
  h.probeEffects();
  status = { ...status, revision: 9, timeout: 90 };
  h.render();
  h.flushEffects();
  const dirty = h.render();
  assert.deepEqual(JSON.parse(JSON.stringify(dirty.services)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(dirty.toolGroups)), []);
  assert.equal(dirty.timeout, 12);
  assert.equal(object(dirty.metadata).name, "Unapplied");
  await invoke(dirty.onSaveServices);
  assert.equal(object(applied).expectedRevision, 7);
});

void test("acknowledged local apply completes even when the optional refresh fails", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  let closed = 0,
    writes = 0;
  let status = {
    ...review,
    toolkit_id: "saved",
    revision: 7,
    connection_id: "grant",
    status: "connected",
    granted_tools: review.accesses.flatMap((access) => access.permitted_tools),
  };
  const h = setupHarness(
    store,
    () => Promise.reject(new Error("No cancel")),
    () => Promise.reject(new Error("No review")),
    () => {},
    {
      status: () => status,
      save: () => {
        writes++;
        status = { ...status, revision: 8, services: [] };
        return Promise.resolve(status);
      },
    },
    null,
    void 0,
    {
      invalidate: () => Promise.reject(new Error("Synthetic read failure")),
      props: {
        onComplete: () => {
          closed++;
        },
      },
    },
  );
  invoke(h.render().onServiceChange, "calendar", false);
  await invoke(h.render().onSaveServices);
  assert.equal(writes, 1);
  assert.equal(closed, 1);
  assert.notEqual(h.render().operationError, "serviceSaveFailed");
});

void test("failed fresh authorization after an exact retry releases cancellation ownership", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  store.value = { ...context("old", "saved"), purpose: "RECOVER" };
  let authorizations = 0;
  const observed = deferred<unknown>();
  const h = setupHarness(
    store,
    () => Promise.resolve({ cancelled: true, publication: null }),
    () => {
      observed.resolve({ ...review, reconnect_toolkit_id: "saved" });
      return observed.promise;
    },
    () => {},
    {
      status: () => ({
        ...review,
        toolkit_id: "saved",
        revision: 7,
        connection_id: "grant",
        status: "connected",
        granted_tools: [],
      }),
      save: () => Promise.reject(new Error("No settings save")),
    },
    () => {
      authorizations += 1;
      return Promise.reject(new Error("Synthetic authorization failure"));
    },
  );
  await observed.promise;
  const output = h.render();
  h.flushEffects();
  await invoke(output.onRetryAuthorization);
  const failed = h.render();
  h.flushEffects();
  assert.equal(object(failed.flow).type, "ERROR");
  assert.equal(failed.cancelling, false);
  await invoke(h.render().onRetryAuthorization);
  assert.equal(authorizations, 2);
});

void test("per-service presets leave other services' group selections unchanged", () => {
  const h = setupHarness(
    new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY),
    () => Promise.reject(new Error("No cancel")),
    () => Promise.reject(new Error("No review")),
    () => {},
    null,
  );
  for (const service of ["calendar", "drive", "gmail"]) {
    invoke(h.render().onServiceChange, service, true);
  }
  invoke(h.render().onGroupChange, "calendar_read", true);
  invoke(h.render().onGroupChange, "gmail_send", true);
  invoke(h.render().onPresetChange, "drive", "read_only");
  assert.deepEqual(JSON.parse(JSON.stringify(h.render().toolGroups)), [
    "calendar_read",
    "gmail_send",
    "drive_read",
  ]);
  invoke(h.render().onPresetChange, "gmail", "clear");
  assert.deepEqual(JSON.parse(JSON.stringify(h.render().toolGroups)), [
    "calendar_read",
    "drive_read",
  ]);
});

void test("retry after pre-navigation APPLY failure retains the pending settings selection", async () => {
  const inputs: unknown[] = [];
  const h = setupHarness(
    new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY),
    () => Promise.reject(new Error("No cancel")),
    () => Promise.reject(new Error("No review")),
    () => {},
    {
      status: () => ({
        ...review,
        toolkit_id: "saved",
        revision: 7,
        connection_id: "grant",
        status: "connected",
        granted_tools: [],
      }),
      save: () => Promise.reject(new Error("No direct save")),
    },
    (input) => {
      inputs.push(input);
      return Promise.reject(new Error("Synthetic pre-navigation failure"));
    },
  );
  invoke(h.render().onServiceChange, "gmail", true);
  invoke(h.render().onGroupChange, "gmail_read", true);
  invoke(h.render().onTimeoutChange, 12);
  invoke(h.render().onMetadataChange, { name: "Pending apply" });
  await invoke(h.render().onSaveServices);
  h.render();
  h.flushEffects();
  await invoke(h.render().onRetryAuthorization);
  assert.equal(inputs.length, 2);
  for (const input of inputs) {
    const desired = object(object(input).desired);
    assert.deepEqual(JSON.parse(JSON.stringify(desired.services)), [
      "calendar",
      "gmail",
    ]);
    assert.deepEqual(JSON.parse(JSON.stringify(desired.tool_groups)), [
      "calendar_read",
      "gmail_read",
    ]);
    assert.equal(desired.timeout, 12);
  }
  assert.equal(object(h.render().metadata).name, "Pending apply");
});

for (const result of ["recovered", "cancelled", "superseded"]) {
  void test(`retained draft survives remount after ${result} authentication`, async () => {
    const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
    store.value = {
      ...context("old", "saved"),
      purpose: "RECOVER",
      phase: "UNKNOWN",
    };
    const draftStore = new BrowserStorageFixture(googleEditor.GOOGLE_DRAFT_KEY);
    const draft: googleEditor.GoogleEditorDraft = {
      handle: "team",
      agentId: "agent",
      toolkitId: "saved",
      attemptId: "old",
      expiresAt: deadline,
      metadata: { ...googleEditor.emptyGoogleMetadata, name: "Unapplied edit" },
      services: ["calendar", "gmail"],
      toolGroups: ["calendar_read", "gmail_read"],
      timeout: 12,
      revision: 7,
      baseline: {
        services: ["calendar"],
        toolGroups: ["calendar_read"],
        timeout: 30,
      },
    };
    let status = {
      ...review,
      toolkit_id: "saved",
      revision: 7,
      connection_id: "old-grant",
      status: "connected",
      granted_tools: [],
    };
    const management = {
      status: () => status,
      save: () => Promise.reject(new Error("No save")),
    };
    const cancelled = deferred<unknown>();
    const h = setupHarness(
      store,
      () => cancelled.promise,
      () => Promise.reject(new Error("No review")),
      () => {},
      management,
      null,
      void 0,
      {
        draft,
        draftStore,
        outcome: () =>
          Promise.resolve({
            toolkit_id: "saved",
            connection_id: "new-grant",
            current: result === "recovered",
          }),
      },
    );
    if (result === "cancelled") {
      const cancellation = invoke(h.render().onCancel);
      cancelled.resolve({ cancelled: true, publication: null });
      await cancellation;
    } else {
      status = {
        ...status,
        revision: result === "recovered" ? 8 : 9,
        connection_id: result === "recovered" ? "new-grant" : "other-grant",
      };
      await invoke(h.render().onCheckOutcome);
    }
    assert.equal(store.value, null);
    assert.equal(object(draftStore.value).attemptId, void 0);
    assert.equal(
      object(draftStore.value).revision,
      result === "recovered" ? 8 : 7,
    );
    h.unmount();
    const reopened = setupHarness(
      store,
      () => Promise.reject(new Error("No cancel")),
      () => Promise.reject(new Error("No review")),
      () => {},
      management,
      null,
      void 0,
      { draftStore },
    ).render();
    assert.equal(object(reopened.metadata).name, "Unapplied edit");
    assert.equal(reopened.timeout, 12);
    assert.deepEqual(JSON.parse(JSON.stringify(reopened.services)), [
      "calendar",
      "gmail",
    ]);
    assert.deepEqual(JSON.parse(JSON.stringify(reopened.toolGroups)), [
      "calendar_read",
      "gmail_read",
    ]);
    assert.equal(reopened.settingsDirty, true);
  });
}
