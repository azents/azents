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
  oauth_request_scopes: googleAccess.googleScopesForServices(["calendar"]),
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
      oauth_request_scopes: googleAccess.googleScopesForServices(["calendar"]),
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
): HookHarness {
  const harness = new HookHarness();
  const google: Record<string, unknown> = {
    preparation: {
      useQuery: () =>
        query({
          status: "configured_unverified",
          client_id: "client",
          callback_url: "https://app.example.invalid/oauth/google/callback",
          picker_status: "not_configured",
          service_access_verified: false,
        }),
    },
    status: { useQuery: () => query(management?.status() ?? null) },
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
  });
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
  void test(`${ownership} consent requests permissions automatically for the enabled services`, async () => {
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
    invoke(output.onAuthorize);
    const input = object(await dispatched.promise);
    assert.deepEqual(JSON.parse(JSON.stringify(object(input.desired))), {
      services: ["drive"],
      oauth_request_scopes: googleAccess.googleScopesForServices(["drive"]),
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
    googleAccess.googleScopesForServices(["calendar"]),
  );
  assert.deepEqual(saved.granted_scopes, review.granted_scopes);
  assert.equal(saved.connection_id, "same-grant");
});

void test("publication preserves an already-reviewed narrow request and its actual partial grant", async () => {
  const store = new BrowserStorageFixture(googleResume.GOOGLE_RESUME_KEY);
  store.value = context();
  const reviewed = deferred<unknown>();
  const dispatched = deferred<unknown>();
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
    (input) => {
      dispatched.resolve(input);
      return Promise.reject(new Error("Synthetic unconfirmed publication."));
    },
  );
  reviewed.resolve(narrow);
  await reviewed.promise;
  const output = h.render();
  h.flushEffects();
  invoke(output.onPublish);
  const settings = object(object(await dispatched.promise).settings);
  assert.deepEqual(
    JSON.parse(JSON.stringify(settings.oauth_request_scopes)),
    narrow.oauth_request_scopes,
  );
  assert.deepEqual(narrow.granted_scopes, review.granted_scopes);
});
