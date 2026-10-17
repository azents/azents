import assert from "node:assert/strict";
import { test } from "node:test";
import { isWindowMessageTarget } from "../../shared/lib/window-message-target.ts";
import {
  deferred,
  HookHarness,
  object,
} from "../../shared/testing/hook-test-harness.ts";
import * as creationState from "../../shared/toolkits/github-user-creation-state.ts";
import * as userState from "../../shared/toolkits/github-user-oauth-state.ts";

for (const family of ["creation", "saved"]) {
  for (const outcome of ["success", "denied"]) {
    for (const personal of [true, false]) {
      void test(`actual GitHub ${family} ${outcome} callback preserves ${personal ? "personal" : "workload"} scope`, async () => {
        const h = new HookHarness();
        const origin = personal
          ? { owner: "user", handle: "workspace" }
          : { handle: "team", agentId: "agent" };
        const key =
          family === "creation"
            ? creationState.GITHUB_USER_CREATION_KEY
            : userState.GITHUB_USER_CONTEXT_KEY;
        const returnPath = personal
          ? `/w/workspace/personal-tools/${family === "creation" ? "new" : "saved/edit"}`
          : "/w/team/agents/agent/settings/capabilities#agent-toolkits";
        const context =
          family === "creation"
            ? {
                ...origin,
                attemptId: "attempt",
                phase: "AUTHORIZING",
                returnPath,
              }
            : { ...origin, toolkitId: "saved", returnPath, returnView: "EDIT" };
        const storage = new Map<string, string>([
          [key, JSON.stringify(context)],
        ]);
        const calls: Array<{ route: string; input: unknown }> = [];
        const routes: unknown[] = [];
        const messages: unknown[] = [];
        const complete = deferred<void>();
        let pending: ReturnType<HookHarness["nativeDeferred"]> | null = null;
        const mutation = (route: string): unknown => ({
          useMutation: () => ({
            mutateAsync: (input: unknown): PromiseLike<unknown> => {
              calls.push({ route, input });
              assert.ok(pending);
              return pending.promise;
            },
          }),
        });
        h.load(
          new URL(
            "./containers/useGitHubUserOAuthCallbackContainer.ts",
            import.meta.url,
          ),
          "useGitHubUserOAuthCallbackContainer",
          {
            react: h.react,
            "@mantine/hooks": {
              readSessionStorageValue: (options: {
                key: string;
                deserialize: (value?: string) => unknown;
              }): unknown => options.deserialize(storage.get(options.key)),
              useSessionStorage: (options: { key: string }): unknown[] => [
                null,
                (value: unknown): void => {
                  storage.set(options.key, JSON.stringify(value));
                },
              ],
            },
            "next/navigation": {
              useRouter: () => ({
                replace: (path: unknown): void => {
                  routes.push(path);
                  complete.resolve();
                },
              }),
            },
            "@/shared/lib/window-message-target": { isWindowMessageTarget },
            "@/shared/toolkits/github-user-creation-state": creationState,
            "../../../shared/toolkits/github-user-oauth-state": userState,
            "@/trpc/client": {
              trpc: {
                toolkit: {
                  githubUserCreation: {
                    exchange: mutation("creation.exchange"),
                    cancel: mutation("creation.cancel"),
                  },
                  githubUser: {
                    exchange: mutation("saved.exchange"),
                    cancel: mutation("saved.cancel"),
                  },
                },
              },
            },
          },
          {
            history: { replaceState: (): void => {} },
            location: {
              pathname: "/oauth/github/user/callback",
              origin: "https://app.test",
            },
            opener: {
              postMessage: (message: unknown): void => {
                messages.push(message);
                if (outcome === "denied") {
                  complete.resolve();
                }
              },
            },
          },
        );
        pending = h.nativeDeferred();
        h.render({
          code: outcome === "success" ? "fixture-code" : null,
          state: `${family === "creation" ? "github_user_create" : "github_user"}.attempt.nonce`,
          providerError: outcome === "denied" ? "access_denied" : null,
        });
        h.flushEffects();
        assert.equal(calls.length, 1);
        const [call] = calls;
        assert.ok(call);
        assert.equal(
          call.route,
          `${family}.${outcome === "success" ? "exchange" : "cancel"}`,
        );
        const input = object(call.input);
        if (personal) {
          assert.equal(input.owner, "user");
          assert.equal(input.handle, "workspace");
          assert.equal(Object.hasOwn(input, "agentId"), false);
        } else {
          assert.equal(input.handle, "team");
          assert.equal(input.agentId, "agent");
        }
        pending.resolve({});
        await complete.promise;
        if (family === "creation") {
          assert.deepEqual(routes, [returnPath]);
          const persisted = creationState.deserializeGitHubUserCreation(
            storage.get(key),
          );
          assert.ok(persisted);
          assert.equal(
            persisted.phase,
            outcome === "success" ? "REVIEW" : "ERROR",
          );
        } else {
          assert.equal(messages.length, 1);
          const persisted = userState.deserializeGitHubUserContext(
            storage.get(key),
          );
          assert.ok(persisted);
          if (outcome === "success") {
            assert.deepEqual(routes, [returnPath]);
            assert.equal(persisted.reviewAttemptId, "attempt");
          } else {
            assert.deepEqual(routes, []);
          }
        }
      });
    }
  }
}
