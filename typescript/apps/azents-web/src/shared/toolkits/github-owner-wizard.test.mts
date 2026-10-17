import assert from "node:assert/strict";
import { test } from "node:test";
import * as identifiers from "../lib/toolkit-identifiers.ts";
import { isRecord } from "../lib/unknown-value.ts";
import {
  BrowserStorageFixture,
  deferred,
  HookHarness,
  invoke,
  object,
} from "../testing/hook-test-harness.ts";
import * as creation from "./github-user-creation-state.ts";
import * as operations from "./github-wizard-operations.ts";
import * as selection from "./github-wizard-selection.ts";
import * as state from "./github-wizard-state.ts";
import * as popup from "./popup-messages.ts";
import * as providerViews from "./provider-config-views.ts";
import * as scopeHelpers from "./toolkit-owner-scope.ts";

for (const scope of [
  { owner: "user", handle: "workspace" },
  { handle: "team" },
  { handle: "team", agentId: "agent" },
] satisfies scopeHelpers.ToolkitOwnerScope[]) {
  void test(`Actual GitHub PAT wizard preserves ${JSON.stringify(scope)} and Runtime injection options`, async () => {
    const h = new HookHarness();
    const storage = new BrowserStorageFixture(
      creation.GITHUB_USER_CREATION_KEY,
    );
    const queries: unknown[] = [];
    const calls: Array<{ route: string; input: unknown }> = [];
    const invalidations: string[] = [];
    const routes: unknown[] = [];
    const completed = deferred<void>();
    let verification: ReturnType<HookHarness["nativeDeferred"]> | null = null;
    const mutation = (route: string): unknown => ({
      useMutation: () => ({
        mutateAsync: (input: unknown): PromiseLike<unknown> => {
          calls.push({ route, input });
          if (route === "verify") {
            assert.ok(verification);
            return verification.promise;
          }
          return Promise.resolve({ id: "saved" });
        },
      }),
    });
    const invalidate = (name: string): unknown => ({
      invalidate: (): Promise<void> => {
        invalidations.push(name);
        return Promise.resolve();
      },
    });
    const toolkit = {
      githubUser: {
        availability: {
          useQuery: (input: unknown): unknown => {
            queries.push(input);
            return {
              isLoading: false,
              isError: false,
              data: {
                platform: "absent",
                platform_modes: {
                  user_account: "absent",
                  installation: "absent",
                },
              },
            };
          },
        },
      },
      githubSetup: { verify: mutation("verify") },
      githubUserCreation: {
        connect: mutation("connect"),
        cancel: mutation("cancel"),
        confirm: mutation("confirm"),
      },
      createConfig: mutation("shared.create"),
      createAgentConfig: mutation("agent.create"),
      getGithubInstallations: mutation("installations"),
    };
    const utils = {
      toolkit: {
        listConfigs: invalidate("shared.list"),
        listAvailableConfigs: invalidate("shared.available"),
        listAgentManagement: invalidate("agent.list"),
      },
      personalToolkit: {
        list: invalidate("personal.list"),
        get: invalidate("personal.get"),
        accessForAgent: invalidate("personal.access"),
      },
    };
    h.load(
      new URL("./containers/useGitHubWizardContainer.ts", import.meta.url),
      "useGitHubWizardContainer",
      {
        react: h.react,
        "@mantine/hooks": {
          ...storage.mantine,
          useInterval: () => ({ start: (): void => {}, stop: (): void => {} }),
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
            replace: (path: unknown): void => {
              routes.push(path);
              completed.resolve();
            },
          }),
        },
        "@/shared/lib/toolkit-identifiers": identifiers,
        "@/shared/lib/unknown-value": { isRecord },
        "@/trpc/client": {
          trpc: {
            toolkit,
            personalToolkit: { create: mutation("personal.create") },
            useUtils: () => utils,
          },
        },
        "../github-user-creation-state": creation,
        "../github-wizard-operations": operations,
        "../github-wizard-selection": selection,
        "../github-wizard-state": state,
        "../popup-messages": popup,
        "../provider-config-views": providerViews,
        "../toolkit-owner-scope": scopeHelpers,
        "./useGitHubWizardProgression": {
          useGitHubWizardProgression: () => ({
            rootRef: { current: null },
            advance: (): void => {},
          }),
        },
      },
      {},
    );
    verification = h.nativeDeferred();
    let view = h.render(scope);
    h.flushEffects();
    invoke(view.onMode, "pat");
    view = h.render();
    invoke(view.onCredentials, {
      token: "fixture-pat",
      appId: "",
      privateKey: "",
      clientId: "",
      clientSecret: "",
      installationIds: [],
    });
    view = h.render();
    invoke(view.onConnect);
    verification.resolve({
      identity: { type: "user", login: "fixture" },
      installations: [],
      connectivity: { status: "ready", message: null },
    });
    await verification.promise;
    view = h.render();
    const settings = {
      ...object(view.settings),
      injectRuntimeEnvironment: true,
      runtimeRiskAcknowledged: true,
    };
    invoke(view.onSettings, settings);
    view = h.render();
    invoke(view.onPublish);
    await completed.promise;
    const create = calls.find((call) => call.route.endsWith(".create"));
    assert.ok(create);
    const input = object(create.input);
    const config = object(input.config);
    assert.equal(config.inject_runtime_environment, true);
    assert.equal(config.github_auth_type, "pat");
    if ("owner" in scope) {
      assert.equal(create.route, "personal.create");
      assert.equal(input.handle, "workspace");
      assert.deepEqual(object(queries[0]), {
        owner: "user",
        handle: "workspace",
      });
      assert.ok(invalidations.includes("personal.access"));
      assert.ok(!invalidations.includes("shared.list"));
      assert.equal(view.sharingScope, "personal");
    } else {
      assert.equal(
        create.route,
        "agentId" in scope ? "agent.create" : "shared.create",
      );
      assert.equal(input.handle, "team");
      assert.equal(Object.hasOwn(input, "owner"), false);
    }
    assert.deepEqual(routes, [
      scopeHelpers.toolkitManagementPath(scope, "saved"),
    ]);
  });
}
