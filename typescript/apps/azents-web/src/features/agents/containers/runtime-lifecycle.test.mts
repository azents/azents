import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HookHarness,
  invoke,
  object,
} from "../../../shared/testing/hook-test-harness.ts";

function fixture(): {
  harness: HookHarness;
  mutations: Array<{ operation: string; input: unknown }>;
  invalidations: Array<{ operation: string; input: unknown }>;
  callbacks: Map<string, Record<string, unknown>>;
} {
  const harness = new HookHarness();
  const mutations: Array<{ operation: string; input: unknown }> = [];
  const invalidations: Array<{ operation: string; input: unknown }> = [];
  const callbacks = new Map<string, Record<string, unknown>>();
  const mutation = (operation: string): unknown => ({
    useMutation: (options: unknown): unknown => {
      callbacks.set(operation, object(options));
      return {
        isPending: false,
        mutate: (input: unknown): void => {
          mutations.push({ operation, input: object(input) });
        },
      };
    },
  });
  const invalidate = (operation: string): unknown => ({
    invalidate: (input: unknown): Promise<void> => {
      invalidations.push({ operation, input: object(input) });
      return Promise.resolve();
    },
  });
  harness.load(
    new URL("./useAgentRuntimeSettingsContainer.ts", import.meta.url),
    "useAgentRuntimeSettingsContainer",
    {
      react: harness.react,
      "@/shared/agent-session/useAgentLifecycle": {
        useAgentLifecycle: (): unknown => ({}),
      },
      "@/shared/lib/runtimeLifecycle": {
        shouldPollRuntimeLifecycle: (): boolean => false,
      },
      "@/shared/runtime-metrics/containers/useRuntimeSystemMetricsContainer": {
        useRuntimeSystemMetricsContainer: (): unknown => ({
          state: { type: "UNAVAILABLE" },
        }),
      },
      "@/trpc/client": {
        trpc: {
          useUtils: (): unknown => ({
            chat: Object.fromEntries(
              [
                "getAgentRuntime",
                "getAgentRuntimeSystemMetrics",
                "getAgentWorkspace",
                "readAgentWorkspacePath",
                "listAgentProjects",
              ].map((name) => [name, invalidate(name)]),
            ),
            agent: {
              get: invalidate("agent.get"),
              list: invalidate("agent.list"),
            },
          }),
          agent: { update: mutation("update") },
          runtimeProfile: {
            list: { useQuery: (): unknown => ({ data: { items: [] } }) },
          },
          chat: {
            getAgentRuntime: {
              useQuery: (): unknown => ({ data: { capability: "managed" } }),
            },
            addAgentRuntime: mutation("add"),
            removeAgentRuntime: mutation("remove"),
            startAgentRuntime: mutation("start"),
            stopAgentRuntime: mutation("stop"),
            restartAgentRuntime: mutation("restart"),
            resetAgentRuntime: mutation("reset"),
          },
        },
      },
    },
    {},
  );
  harness.render({
    handle: "workspace",
    agent: { id: "agent", runtime_profile_id: "profile" },
  });
  return { harness, mutations, invalidations, callbacks };
}

for (const action of [
  { operation: "start", handler: "onStart", confirmation: null },
  { operation: "stop", handler: "onStop", confirmation: null },
  {
    operation: "restart",
    handler: "onConfirmRestart",
    confirmation: "onOpenRestartConfirm",
  },
  {
    operation: "reset",
    handler: "onConfirmReset",
    confirmation: "onOpenResetConfirm",
  },
]) {
  for (const outcome of ["success", "error"]) {
    void test(`${action.operation} routes once and handles ${outcome} at the mutation boundary`, async () => {
      const { harness, mutations, invalidations, callbacks } = fixture();
      let view = harness.render();
      if (action.confirmation !== null) {
        invoke(view[action.confirmation]);
        view = harness.render();
        assert.equal(view[`${action.operation}ConfirmOpen`], true);
        assert.deepEqual(mutations, []);
      }
      invoke(view[action.handler]);
      view = harness.render();
      assert.equal(view.lifecycleAction, action.operation);
      assert.deepEqual(mutations, [
        {
          operation: action.operation,
          input: { handle: "workspace", agentId: "agent" },
        },
      ]);
      assert.deepEqual(invalidations, []);
      const callback = callbacks.get(action.operation);
      assert.ok(callback);
      if (outcome === "success") {
        await invoke(callback.onSuccess);
        assert.deepEqual(invalidations, [
          {
            operation: "getAgentRuntime",
            input: { handle: "workspace", agentId: "agent" },
          },
          {
            operation: "getAgentRuntimeSystemMetrics",
            input: { handle: "workspace", agentId: "agent" },
          },
          {
            operation: "agent.get",
            input: { handle: "workspace", agentId: "agent" },
          },
          { operation: "agent.list", input: { handle: "workspace" } },
          { operation: "getAgentWorkspace", input: { agentId: "agent" } },
          { operation: "readAgentWorkspacePath", input: { agentId: "agent" } },
          { operation: "listAgentProjects", input: { agentId: "agent" } },
        ]);
        view = harness.render();
        assert.equal(view.restartConfirmOpen, false);
        assert.equal(view.resetConfirmOpen, false);
        assert.equal(view.actionError, null);
      } else {
        invoke(callback.onError, "Synthetic request failure");
        view = harness.render();
        assert.equal(view.actionError, "Runtime request failed.");
        assert.deepEqual(invalidations, []);
      }
      assert.equal(view.lifecycleAction, null);
      assert.equal(mutations.length, 1);
    });
  }
}
