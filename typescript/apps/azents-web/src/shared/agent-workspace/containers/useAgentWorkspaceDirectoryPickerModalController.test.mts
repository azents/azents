import assert from "node:assert/strict";
import test from "node:test";
import { HookHarness, invoke } from "../../testing/hook-test-harness.ts";

void test("directory picker close resets confirmation before notifying its owner", () => {
  const harness = new HookHarness();
  harness.load(
    new URL(
      "./useAgentWorkspaceDirectoryPickerModalController.tsx",
      import.meta.url,
    ),
    "useAgentWorkspaceDirectoryPickerModalController",
    {
      react: harness.react,
      "next-intl": {
        useTranslations: (): ((key: string) => string) => (key) => key,
      },
    },
    {},
  );
  const observations: unknown[] = [];
  let view = harness.render({
    opened: true,
    state: { type: "RUNTIME_STOPPED" },
    onClose: (): void => {
      observations.push(harness.render().restartConfirmOpen);
    },
  });
  invoke(view.setRestartConfirmOpen, true);
  view = harness.render();
  assert.equal(view.restartConfirmOpen, true);
  invoke(view.closePicker);
  assert.deepEqual(observations, [false]);
  assert.equal(harness.render().restartConfirmOpen, false);
});
