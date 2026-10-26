import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HookHarness,
  invoke,
  object,
} from "../../../shared/testing/hook-test-harness.ts";

function fixture(enabled: boolean | null): {
  harness: HookHarness;
  mutations: unknown[];
  setEnabled: (value: boolean) => void;
} {
  const harness = new HookHarness();
  const mutations: unknown[] = [];
  let browserEnabled = enabled;
  const configuration = {
    intent_id: "intent-1",
    requested: "patchright",
    state: "failed",
    reason_code: "browser_configuration_unsupported",
  };
  harness.load(
    new URL("./useAgentBrowserChoice.ts", import.meta.url),
    "useAgentBrowserChoice",
    {
      react: harness.react,
      "@/shared/agent-session/useAgentLifecycle": {
        useAgentLifecycle: (): unknown => ({
          agent: {
            browser_enabled: browserEnabled,
            toolkit_management_available: true,
          },
          readOnly: false,
        }),
      },
      "@/trpc/client": {
        trpc: {
          useUtils: (): unknown => ({}),
          agent: {
            getBrowserConfiguration: {
              useQuery: (): unknown => ({
                data: configuration,
                isError: false,
              }),
            },
            replaceBrowserConfiguration: {
              useMutation: (): unknown => ({
                isPending: false,
                error: null,
                reset: (): void => {},
                mutate: (input: unknown): void => {
                  mutations.push(input);
                },
              }),
            },
          },
        },
      },
    },
    {},
  );
  harness.render({ handle: "workspace", agentId: "agent-1", disabled: false });
  return {
    harness,
    mutations,
    setEnabled: (value): void => {
      browserEnabled = value;
    },
  };
}

for (const enabled of [false, null]) {
  void test(`browser ${String(enabled)} blocks engine selection and retry`, () => {
    const { harness, mutations } = fixture(enabled);
    let view = harness.render();
    assert.equal(object(view.state).browserEnabled, false);
    assert.equal(object(view.state).readOnly, true);
    invoke(view.onSelect, "camoufox");
    view = harness.render();
    assert.equal(object(view.state).confirmation, null);
    invoke(view.onConfirm);
    invoke(view.onRetry);
    view = harness.render();
    assert.equal(object(view.state).confirmation, null);
    invoke(view.onConfirm);
    assert.equal(mutations.length, 0);
  });
}

void test("disabling Browser blocks an already drafted engine confirmation", () => {
  const { harness, mutations, setEnabled } = fixture(true);
  let view = harness.render();
  invoke(view.onSelect, "camoufox");
  view = harness.render();
  assert.equal(object(view.state).confirmation, "camoufox");
  setEnabled(false);
  view = harness.render();
  assert.equal(object(view.state).confirmation, null);
  invoke(view.onConfirm);
  assert.equal(mutations.length, 0);
});

void test("enabled Browser preserves engine selection and explicit retry", () => {
  const { harness, mutations } = fixture(true);
  let view = harness.render();
  invoke(view.onSelect, "camoufox");
  view = harness.render();
  invoke(view.onConfirm);
  assert.equal(object(mutations[0]).implementation, "camoufox");
  assert.equal(object(mutations[0]).retry, false);
  invoke(view.onRetry);
  view = harness.render();
  invoke(view.onConfirm);
  assert.equal(object(mutations[1]).implementation, "patchright");
  assert.equal(object(mutations[1]).retry, true);
});
