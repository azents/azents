import assert from "node:assert/strict";
import { test } from "node:test";
import { skipToken } from "@tanstack/react-query";
import * as credentialEdits from "../lib/redacted-credentials.ts";
import * as identifiers from "../lib/toolkit-identifiers.ts";
import {
  deferred,
  HookHarness,
  invoke,
  object,
} from "../testing/hook-test-harness.ts";
import * as creationState from "./github-user-creation-state.ts";
import * as githubCredentials from "./github-user-credentials.ts";
import * as googleResume from "./google-resume.ts";
import * as popup from "./popup-messages.ts";
import * as providerViews from "./provider-config-views.ts";
import * as projection from "./toolkit-config-projection.ts";
import * as lifecycle from "./toolkit-form-lifecycle.ts";
import type { ToolkitOwnerScope } from "./toolkit-owner-scope.ts";

const providers = [
  "mcp",
  "notion",
  "sentry",
  "aws",
  "gcp",
  "kubernetes",
  "google_analytics",
  "brave_search",
  "github",
  "google",
];
interface Fixture {
  h: HookHarness;
  calls: Array<{ route: string; input: unknown }>;
  reads: Array<{ route: string; input: unknown }>;
  invalidations: string[];
  routes: string[];
  completed: string[];
  opened: string[];
  popupReady: Promise<void>;
  invalidated: Promise<void>;
  current: () => Record<string, unknown>;
  set: (key: string, value: unknown) => void;
  fail: (failure: boolean) => void;
}
function formFixture(
  scope: ToolkitOwnerScope,
  provider: string,
  toolkitId: string | null,
): Fixture {
  const h = new HookHarness();
  const calls: Fixture["calls"] = [];
  const reads: Fixture["reads"] = [];
  const invalidations: string[] = [];
  const routes: string[] = [];
  const completed: string[] = [];
  const opened: string[] = [];
  const popupReady = deferred<void>();
  const invalidated = deferred<void>();
  let failed = false;
  const config =
    provider === "google"
      ? {
          services: ["calendar"],
          oauth_request_scopes: [
            "openid",
            "email",
            "https://www.googleapis.com/auth/calendar.events.readonly",
          ],
          timeout: 30,
        }
      : provider === "github"
        ? {
            github_auth_type: "pat",
            inject_runtime_environment: true,
            timeout: 30,
          }
        : provider === "mcp"
          ? {
              server_url: "https://fixture.test",
              auth_type: "oauth2",
              timeout: 30,
            }
          : { timeout: 30, configured_option: "preserved" };
  const saved = {
    id: "saved",
    toolkit_type: provider,
    name: "Saved",
    slug: "saved",
    description: null,
    prompt: null,
    config,
    has_credentials: true,
    enabled: true,
    always_expose_tools: true,
    ...("owner" in scope
      ? {
          owner: {
            kind: "user",
            user_id: "fixture-user",
            workspace_id: "workspace-id",
          },
          access_mode: "all",
          selected_agent_ids: [],
          readiness: "ready",
        }
      : { workspace_id: "workload" }),
  };
  const query = (route: string): unknown => ({
    useQuery: (input: unknown): unknown => {
      reads.push({ route, input });
      return {
        isLoading: false,
        isError: false,
        data: input === skipToken ? null : saved,
      };
    },
  });
  const mutation = (route: string): unknown => ({
    useMutation: () => ({
      isPending: false,
      mutateAsync: (input: unknown): Promise<unknown> => {
        calls.push({ route, input });
        return failed
          ? Promise.reject(new Error("Fixture save rejected"))
          : Promise.resolve(
              route.endsWith("connect")
                ? { authorization_url: "https://oauth.test/authorize" }
                : saved,
            );
      },
    }),
  });
  const invalidator = (route: string): unknown => ({
    invalidate: (): Promise<void> => {
      invalidations.push(route);
      invalidated.resolve();
      return Promise.resolve();
    },
    fetch: (): Promise<unknown> =>
      Promise.reject(new Error("Fixture post-commit read unavailable")),
  });
  const toolkit = {
    listToolkits: {
      useQuery: () => ({
        isLoading: false,
        isError: false,
        data: {
          items: providers.map((slug) => ({
            slug,
            name: slug,
            description: `${slug} definition`,
          })),
        },
      }),
    },
    getConfig: query("shared"),
    getAgentConfig: query("agent"),
    createConfig: mutation("shared.create"),
    updateConfig: mutation("shared.update"),
    createAgentConfig: mutation("agent.create"),
    updateAgentConfig: mutation("agent.update"),
    connectOauth: mutation("shared.connect"),
    connectAgentOauth: mutation("agent.connect"),
    disconnectOauth: mutation("shared.disconnect"),
    disconnectAgentOauth: mutation("agent.disconnect"),
  };
  const personalToolkit = {
    get: query("personal"),
    create: mutation("personal.create"),
    update: mutation("personal.update"),
    connectOauth: mutation("personal.connect"),
    disconnectOauth: mutation("personal.disconnect"),
  };
  const utils = {
    toolkit: {
      getConfig: invalidator("shared.get"),
      getAgentConfig: invalidator("agent.get"),
      listConfigs: invalidator("shared.list"),
      listAgentManagement: invalidator("agent.list"),
    },
    personalToolkit: {
      get: invalidator("personal.get"),
      list: invalidator("personal.list"),
      accessForAgent: invalidator("personal.access"),
    },
  };
  const api = { toolkit, personalToolkit, useUtils: () => utils };
  const adapter = h.load(
    new URL("./containers/useToolkitOwnerAdapter.ts", import.meta.url),
    "useToolkitOwnerAdapter",
    {
      "@tanstack/react-query": { skipToken },
      "@/trpc/client": { trpc: api },
      "@/shared/lib/toolkit-identifiers": identifiers,
      "../toolkit-form-lifecycle": lifecycle,
    },
    {},
  );
  let values: Record<string, unknown> = {};
  const form = {
    getValues: (): unknown => values,
    setFieldValue: (key: string, value: unknown): void => {
      values[key] = value;
    },
    setValues: (patch: unknown): void => {
      values = { ...values, ...object(patch) };
    },
    resetDirty: (): void => {},
    onSubmit:
      (handler: unknown): (() => unknown) =>
      () =>
        invoke(handler, values),
  };
  h.load(
    new URL("./containers/useToolkitFormContainer.ts", import.meta.url),
    "useToolkitFormContainer",
    {
      react: h.react,
      "@mantine/form": {
        useForm: (options: unknown): unknown => {
          if (Object.keys(values).length === 0) {
            values = object(object(options).initialValues);
          }
          return form;
        },
      },
      "@mantine/hooks": {
        readSessionStorageValue: () => null,
        useWindowEvent: (): void => {},
      },
      "next-intl": {
        useTranslations:
          () =>
          (key: string): string =>
            key,
      },
      "next/navigation": {
        useRouter: () => ({
          push: (path: string): void => {
            routes.push(path);
          },
        }),
      },
      "@/trpc/client": { trpc: api },
      "@/shared/lib/redacted-credentials": credentialEdits,
      "@/shared/lib/toolkit-identifiers": identifiers,
      "../github-user-creation-state": creationState,
      "../github-user-credentials": githubCredentials,
      "../google-resume": googleResume,
      "../popup-messages": popup,
      "../provider-config-views": providerViews,
      "../toolkit-config-projection": projection,
      "../toolkit-form-lifecycle": lifecycle,
      "../schemas": {
        toolkitFormSchema: { safeParse: () => ({ success: true }) },
      },
      "./useToolkitOwnerAdapter": { useToolkitOwnerAdapter: adapter },
    },
    {
      open: (url: string): void => {
        opened.push(url);
        popupReady.resolve();
      },
    },
  );
  h.render({
    ...scope,
    ...(toolkitId != null && { toolkitId }),
    initialToolkitType: provider,
    onComplete: (): void => {
      completed.push("complete");
    },
  });
  h.flushEffects();
  h.render();
  return {
    h,
    calls,
    reads,
    invalidations,
    routes,
    completed,
    opened,
    popupReady: popupReady.promise,
    invalidated: invalidated.promise,
    current: () => values,
    set: form.setFieldValue,
    fail: (failure): void => {
      failed = failure;
    },
  };
}

for (const provider of providers) {
  for (const scope of [
    { owner: "user", handle: "workspace" },
    { handle: "team" },
    { handle: "team", agentId: "agent" },
  ] satisfies ToolkitOwnerScope[]) {
    void test(`Common ${provider} edit form routes the exact ${JSON.stringify(scope)} source`, async () => {
      const f = formFixture(scope, provider, "saved");
      const view = f.h.render();
      assert.deepEqual(object(view.scope), scope);
      const family =
        "owner" in scope
          ? "personal"
          : scope.agentId != null
            ? "agent"
            : "shared";
      const active = f.reads.filter((read) => read.input !== skipToken);
      assert.ok(active.every((read) => read.route === family));
      if (family === "personal") {
        assert.equal(
          Object.hasOwn(object(object(view.formState).config), "workspace_id"),
          false,
        );
        assert.equal(object(object(view.formState).config).access_mode, "all");
      }
      f.set("name", "Changed");
      await invoke(f.h.render().onSubmit);
      assert.equal(f.calls.length, 1);
      const call = f.calls[0];
      assert.ok(call);
      assert.equal(call.route, `${family}.update`);
      const input = object(call.input);
      assert.equal(input.name, "Changed");
      assert.equal(input.alwaysExposeTools, true);
      if (family === "personal") {
        assert.equal(input.handle, "workspace");
        assert.equal(Object.hasOwn(input, "agentId"), false);
        assert.ok(f.invalidations.includes("personal.access"));
        assert.ok(!f.invalidations.includes("shared.list"));
      }
      if (provider === "google") {
        assert.equal(Object.hasOwn(input, "config"), false);
      } else {
        assert.ok(Object.hasOwn(input, "config"));
      }
      if (provider === "github") {
        assert.equal(object(input.config).inject_runtime_environment, true);
      }
      assert.equal(object(f.h.render().mutationState).error, null);
    });
  }
  if (provider !== "google" && provider !== "github") {
    void test(`Common personal ${provider} creation keeps the catalog and Provider config`, async () => {
      const f = formFixture(
        { owner: "user", handle: "workspace" },
        provider,
        null,
      );
      assert.ok(f.reads.every((read) => read.input === skipToken));
      const view = f.h.render();
      assert.equal(
        Array.isArray(view.toolOptions) && view.toolOptions.length,
        providers.length,
      );
      f.set("name", "New personal");
      f.set("config", { provider_option: "unchanged", timeout: 31 });
      await invoke(f.h.render().onSubmit);
      const call = f.calls[0];
      assert.ok(call);
      assert.equal(call.route, "personal.create");
      assert.equal(
        object(object(call.input).config).provider_option,
        "unchanged",
      );
      assert.deepEqual(f.routes, ["/w/workspace/personal-tools"]);
    });
  }
}
for (const scope of [
  { owner: "user", handle: "workspace" },
  { handle: "team" },
  { handle: "team", agentId: "agent" },
] satisfies ToolkitOwnerScope[]) {
  void test(`Common MCP form connects and disconnects only ${JSON.stringify(scope)}`, async () => {
    const f = formFixture(scope, "mcp", "saved");
    invoke(f.h.render().onConnectOauth);
    await f.popupReady;
    assert.deepEqual(f.opened, ["https://oauth.test/authorize"]);
    invoke(f.h.render().onAskDisconnectOauth);
    if ("owner" in scope) {
      assert.equal(f.h.render().oauthDisconnectConfirmation, true);
      assert.equal(
        f.calls.filter((call) => call.route.endsWith("disconnect")).length,
        0,
      );
      invoke(f.h.render().onDismissDisconnectOauth);
      assert.equal(f.h.render().oauthDisconnectConfirmation, false);
      invoke(f.h.render().onAskDisconnectOauth);
      invoke(f.h.render().onDisconnectOauth);
    }
    await f.invalidated;
    const family =
      "owner" in scope
        ? "personal"
        : scope.agentId != null
          ? "agent"
          : "shared";
    assert.deepEqual(
      f.calls.map((call) => call.route),
      [`${family}.connect`, `${family}.disconnect`],
    );
    if ("owner" in scope) {
      assert.ok(
        f.calls.every(
          (call) =>
            Object.hasOwn(object(call.input), "toolkitId") &&
            object(call.input).handle === "workspace",
        ),
      );
      assert.ok(f.invalidations.includes("personal.access"));
    }
  });
}
void test("New staged Google and GitHub forms never bypass their common review Wizards", async () => {
  for (const provider of ["google", "github"]) {
    const f = formFixture(
      { owner: "user", handle: "workspace" },
      provider,
      null,
    );
    await invoke(f.h.render().onSubmit);
    assert.deepEqual(f.calls, []);
    assert.deepEqual(f.routes, []);
  }
});
void test("A failed personal save retains the draft; cancel never changes access or credentials", async () => {
  const f = formFixture({ owner: "user", handle: "workspace" }, "mcp", "saved");
  f.set("name", "Unsaved local name");
  f.fail(true);
  await invoke(f.h.render().onSubmit);
  assert.equal(f.current().name, "Unsaved local name");
  assert.ok(object(f.h.render().mutationState).error);
  assert.deepEqual(f.routes, []);
  assert.deepEqual(f.invalidations, []);
  const count = f.calls.length;
  invoke(f.h.render().onCancel);
  assert.equal(f.calls.length, count);
  assert.deepEqual(f.routes, ["/w/workspace/personal-tools"]);
});
