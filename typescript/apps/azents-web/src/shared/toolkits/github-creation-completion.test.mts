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
  { handle: "team" },
  { handle: "team", agentId: "agent" },
] satisfies scopeHelpers.ToolkitOwnerScope[]) {
  for (const action of ["close", "publish"] as const) {
    void test(`Actual creation ${action} retains exact ${JSON.stringify(scope)} and clears only its attempt`, async () => {
      const h = new HookHarness();
      const storage = new BrowserStorageFixture(
        creation.GITHUB_USER_CREATION_KEY,
      );
      storage.value = {
        ...scope,
        attemptId: "reviewed-attempt",
        phase: "REVIEW",
        returnPath: creation.creationReturnPath(scope),
      };
      const calls: Array<{ route: string; input: unknown }> = [];
      const completed = deferred<void>();
      let review: ReturnType<HookHarness["nativeDeferred"]> | null = null;
      let app: ReturnType<HookHarness["nativeDeferred"]> | null = null;
      const mutation = (route: string): unknown => ({
        useMutation: () => ({
          mutateAsync: (input: unknown): Promise<unknown> => {
            calls.push({ route, input });
            return Promise.resolve({ toolkit_id: "published" });
          },
        }),
      });
      const invalidate = { invalidate: (): Promise<void> => Promise.resolve() };
      h.load(
        new URL("./containers/useGitHubWizardContainer.ts", import.meta.url),
        "useGitHubWizardContainer",
        {
          react: h.react,
          "@mantine/hooks": {
            ...storage.mantine,
            useInterval: () => ({
              start: (): void => {},
              stop: (): void => {},
            }),
          },
          "next-intl": {
            useTranslations:
              () =>
              (key: string): string =>
                key,
          },
          "next/navigation": {
            useRouter: () => ({
              replace: (): void => completed.resolve(),
              push: (): void => completed.resolve(),
            }),
          },
          "@/shared/lib/toolkit-identifiers": identifiers,
          "@/shared/lib/unknown-value": { isRecord },
          "@/trpc/client": {
            trpc: {
              toolkit: {
                githubUser: {
                  availability: {
                    useQuery: () => ({
                      isLoading: false,
                      isError: false,
                      data: {
                        platform_modes: {
                          user_account: "absent",
                          installation: "absent",
                        },
                      },
                    }),
                  },
                },
                githubSetup: { verify: mutation("verify") },
                githubUserCreation: {
                  connect: mutation("connect"),
                  cancel: mutation("cancel"),
                  confirm: mutation("confirm"),
                },
                createConfig: mutation("create"),
                createAgentConfig: mutation("agent.create"),
                getGithubInstallations: mutation("installations"),
              },
              personalToolkit: { create: mutation("personal.create") },
              useUtils: () => ({
                toolkit: {
                  githubUserCreation: {
                    review: {
                      fetch: (input: unknown): PromiseLike<unknown> => {
                        calls.push({ route: "review", input });
                        assert.ok(review);
                        return review.promise;
                      },
                    },
                    app: {
                      fetch: (input: unknown): PromiseLike<unknown> => {
                        calls.push({ route: "app", input });
                        assert.ok(app);
                        return app.promise;
                      },
                    },
                  },
                  listConfigs: invalidate,
                  listAvailableConfigs: invalidate,
                  listAgentManagement: invalidate,
                },
              }),
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
      review = h.nativeDeferred();
      app = h.nativeDeferred();
      h.render(scope);
      h.flushEffects();
      const candidate = {
        attempt_id: "reviewed-attempt",
        account_id: 42,
        account_login: "fixture-user",
        app_id: "123",
        source: "byoa_user",
        sharing_scope: "agentId" in scope ? "agent_only" : "workspace_shared",
      };
      review.resolve({
        name: "Reviewed GitHub",
        slug: "reviewed",
        description: null,
        prompt: null,
        enabled: true,
        always_expose_tools: false,
        config: {
          github_auth_type: "github_app_user",
          toolsets: ["actions"],
          timeout: 30,
          inject_runtime_environment: true,
        },
        candidate,
      });
      await review.promise;
      app.resolve({
        app: { app_id: "123", name: "Fixture", slug: "fixture" },
      });
      await app.promise;
      let view = h.render();
      assert.equal(object(view.connection).type, "CANDIDATE");
      assert.equal(view.canContinue, true);
      assert.deepEqual(
        calls.map((call) => call.route),
        ["review", "app"],
      );
      if (action === "publish") {
        invoke(view.onSettings, {
          ...object(view.settings),
          runtimeRiskAcknowledged: true,
        });
        view = h.render();
        invoke(view.onPublish);
      } else {
        invoke(view.onClose);
      }
      await completed.promise;
      assert.equal(storage.value, null);
      const terminal = calls.filter((call) =>
        ["confirm", "cancel", "create", "agent.create"].includes(call.route),
      );
      assert.equal(terminal.length, 1);
      const [call] = terminal;
      assert.ok(call);
      assert.equal(call.route, action === "publish" ? "confirm" : "cancel");
      const input = object(call.input);
      assert.equal(input.handle, scope.handle);
      assert.equal(input.agentId, "agentId" in scope ? scope.agentId : void 0);
      assert.equal(input.attemptId, "reviewed-attempt");
      if (action === "publish") {
        const settings = object(input.settings);
        assert.equal(settings.inject_runtime_environment, true);
        assert.equal(settings.runtime_risk_acknowledged, true);
        assert.ok(Array.isArray(settings.toolsets));
        assert.deepEqual(Array.from(settings.toolsets), ["actions"]);
      }
      h.unmount();
      assert.equal(
        calls.filter((item) => ["confirm", "cancel"].includes(item.route))
          .length,
        1,
      );
    });
  }
}
