import assert from "node:assert/strict";
import test from "node:test";
import {
  HookHarness,
  invoke,
} from "../../../shared/testing/hook-test-harness.ts";

void test("focused sidebar owns rename receipts, clear, archive and color-mode wiring", async () => {
  const hook = new HookHarness();
  const colors: string[] = [];
  const schemes: string[] = [];
  const renamed: unknown[][] = [];
  const archived: unknown[] = [];
  let logout = 0;
  hook.load(
    new URL("./useAgentFocusedSidebar.ts", import.meta.url),
    "useAgentFocusedSidebar",
    {
      react: hook.react,
      "next/navigation": { usePathname: () => "/w/test/agents/agent/sessions" },
      "@mantine/core": {
        useMantineColorScheme: () => ({
          setColorScheme: (v: string) => schemes.push(v),
        }),
      },
      "@/shared/providers/color-mode": {
        useColorMode: () => ({
          mode: "dark",
          preference: "system",
          setColorMode: (v: string) => colors.push(v),
        }),
      },
      "@/shared/providers/locale": { useLocale: () => ({ locale: "ko" }) },
    },
    {},
  );
  const props = {
    handle: "test",
    agent: { id: "agent" },
    currentUser: null,
    adminAccessUrl: null,
    loggingOut: false,
    onLogout: () => {
      logout += 1;
    },
    onRenameSession: (...args: unknown[]): Promise<void> => {
      renamed.push(args);
      return Promise.resolve();
    },
    onArchiveSession: (id: unknown) => archived.push(id),
  };
  let view = hook.render(props);
  invoke(view.handleOpenRename, { id: "session", title: "Original" });
  view = hook.render();
  assert.equal(view.editingTitle, "Original");
  invoke(view.setEditingTitle, "  Trimmed  ");
  view = hook.render();
  await invoke(view.handleSubmitRename);
  view = hook.render();
  assert.deepEqual(renamed, [["session", "Trimmed"]]);
  assert.equal(view.editingSession, null);
  assert.equal(view.editingTitle, "");
  invoke(view.handleOpenRename, { id: "session", title: "Original" });
  view = hook.render();
  await invoke(view.handleClearTitle);
  assert.deepEqual(renamed[1], ["session", null]);
  invoke(view.setArchiveTarget, { id: "session" });
  view = hook.render();
  invoke(view.handleConfirmArchive);
  view = hook.render();
  assert.deepEqual(archived, ["session"]);
  assert.equal(view.archiveTarget, null);
  invoke(view.handleSelectColorMode, "system");
  invoke(view.handleSelectColorMode, "light");
  invoke(view.handleLogout);
  assert.deepEqual(colors, ["system", "light"]);
  assert.deepEqual(schemes, ["auto", "light"]);
  assert.equal(logout, 1);
});
