import assert from "node:assert/strict";
import test from "node:test";
import { shouldShowAgentTerminalSettings } from "./terminalSettingsVisibility.ts";

void test("create exposes Terminal settings only after selecting a Runtime Profile", () => {
  assert.equal(
    shouldShowAgentTerminalSettings({
      type: "CREATE",
      runtimeProfileId: null,
    }),
    false,
  );
  assert.equal(
    shouldShowAgentTerminalSettings({
      type: "CREATE",
      runtimeProfileId: "runtime-profile-1",
    }),
    true,
  );
});

void test("edit exposes Terminal settings only for managed Runtime capability", () => {
  assert.equal(
    shouldShowAgentTerminalSettings({
      type: "EDIT",
      runtimeCapability: "managed",
    }),
    true,
  );
  assert.equal(
    shouldShowAgentTerminalSettings({
      type: "EDIT",
      runtimeCapability: "none",
    }),
    false,
  );
  assert.equal(
    shouldShowAgentTerminalSettings({
      type: "EDIT",
      runtimeCapability: "removing",
    }),
    false,
  );
});
