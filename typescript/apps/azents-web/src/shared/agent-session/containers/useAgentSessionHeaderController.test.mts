import assert from "node:assert/strict";
import test from "node:test";
import { HookHarness, invoke } from "../../testing/hook-test-harness.ts";

function fixture(): { harness: HookHarness; titles: string[] } {
  const harness = new HookHarness();
  const titles: string[] = [];
  harness.load(
    new URL("./useAgentSessionHeaderController.tsx", import.meta.url),
    "useAgentSessionHeaderController",
    {
      react: harness.react,
      "@mantine/hooks": {
        useDocumentTitle: (title: string): void => {
          titles.push(title);
        },
      },
      "next-intl": {
        useTranslations: (): ((key: string) => string) => (key) => key,
      },
      "../AgentFocusedShellMobileNav": {
        useAgentFocusedShellMobileNav: (): null => null,
      },
    },
    {},
  );
  return { harness, titles };
}

void test("session header trims titles, exposes pending receipt, closes after notification and clears with null", async () => {
  const { harness, titles } = fixture();
  const receipt = harness.nativeDeferred();
  const calls: unknown[] = [];
  const updated = { id: "session", title: "Renamed" };
  let notifiedWhileOpen = false;
  let view = harness.render({
    agent: { id: "agent" },
    session: { id: "session", title: "Before" },
    onUpdateTitle: (title: unknown): PromiseLike<unknown> => {
      calls.push(title);
      return receipt.promise;
    },
    onSessionTitleChange: (session: unknown): void => {
      assert.equal(session, updated);
      notifiedWhileOpen = harness.render().editingOpened === true;
    },
    onTogglePanel: (): void => {},
    panelOpened: false,
  });
  harness.flushEffects();
  invoke(view.handleOpenRename);
  view = harness.render();
  invoke(view.setEditingTitle, "  ");
  await invoke(harness.render().handleSubmitRename);
  assert.deepEqual(calls, []);
  invoke(view.setEditingTitle, "  Renamed  ");
  view = harness.render();
  const action = invoke(view.handleSubmitRename);
  assert.equal(harness.render().renameBusy, true);
  receipt.resolve(updated);
  await action;
  view = harness.render();
  assert.deepEqual(calls, ["Renamed"]);
  assert.equal(notifiedWhileOpen, true);
  assert.equal(view.editingOpened, false);
  assert.equal(view.renameBusy, false);
  assert.equal(view.editingTitle, "");
  assert.equal(view.session, updated);
  assert.ok(titles.includes("Renamed - Azents"));
  await invoke(view.handleClearTitle);
  assert.deepEqual(calls, ["Renamed", null]);
});

void test("session header retains failed rename draft and synchronizes refreshed parent session", async () => {
  const { harness } = fixture();
  const initial = { id: "session", title: null, primary_kind: "team_primary" };
  const props = {
    agent: { id: "agent" },
    session: initial,
    onUpdateTitle: (): Promise<never> => Promise.reject(new Error("Rejected.")),
    onTogglePanel: (): void => {},
    panelOpened: false,
  };
  let view = harness.render(props);
  harness.flushEffects();
  assert.equal(view.sessionTitle, "sessions.primary");
  invoke(view.handleOpenRename);
  invoke(harness.render().setEditingTitle, "Keep draft");
  let error: unknown = null;
  try {
    await invoke(harness.render().handleSubmitRename);
  } catch (caught) {
    error = caught;
  }
  assert.ok(error instanceof Error);
  view = harness.render();
  assert.equal(view.editingOpened, true);
  assert.equal(view.editingTitle, "Keep draft");
  assert.equal(view.renameBusy, false);
  const refreshed = { ...initial, title: "Remote title" };
  harness.render({ ...props, session: refreshed });
  harness.flushEffects();
  assert.equal(harness.render().session, refreshed);
});
