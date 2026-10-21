import assert from "node:assert/strict";
import { test } from "node:test";
import { adminNavigation } from "../lib/admin-navigation.ts";
import { getPublicRoutePath } from "../lib/auth-policy.ts";
import { HookHarness, invoke, record } from "../testing/hook-harness.ts";

function setup(desktop: boolean): { harness: HookHarness; calls: unknown[] } {
  const harness = new HookHarness();
  const calls: unknown[] = [];
  harness.load(
    new URL("./useAdminShellContainer.ts", import.meta.url),
    "useAdminShellContainer",
    {
      react: harness.react,
      "@mantine/core": {
        useMantineColorScheme: () => ({
          setColorScheme: (value: string): void => {
            calls.push(["scheme", value]);
          },
        }),
      },
      "@mantine/hooks": {
        useHash: () => ["#audit", (): void => {}],
        useMediaQuery: () => desktop,
        useDisclosure: () => [
          true,
          {
            toggle: (): void => {
              calls.push("toggle");
            },
            close: (): void => {
              calls.push("close");
            },
          },
        ],
      },
      "@refinedev/core": {
        useGetIdentity: () => ({
          data: { id: "preview-admin", name: "Admin", avatar: "" },
        }),
        useLogout: () => ({
          mutate: (): void => {
            calls.push("logout");
          },
        }),
      },
      "next/navigation": {
        usePathname: () => "/gateway/admin/system-settings",
      },
      "@/config/client": {
        useConfig: () => ({
          publicBaseUrl: "https://example.invalid/gateway/admin/",
        }),
      },
      "@/providers/color-mode": {
        useColorMode: () => ({
          mode: "light",
          preference: "system",
          setColorMode: (value: string): void => {
            calls.push(["preference", value]);
          },
        }),
      },
      "../lib/admin-navigation": { adminNavigation },
      "../lib/auth-policy": { getPublicRoutePath },
    },
  );
  return { harness, calls };
}

void test("shared shell projects the current fragment and preserves theme and logout collaborators", () => {
  const { harness, calls } = setup(false);
  const output = harness.render({ children: "current screen" });
  harness.flushEffects();
  assert.deepEqual(calls, []);
  assert.equal(output.children, "current screen");
  assert.equal(output.homeHref, "/gateway/admin/");
  assert.equal(record(output.location).label, "Audit log");
  invoke(output.onPreferenceChange, "system");
  invoke(output.onPreferenceChange, "dark");
  invoke(output.onLogout);
  assert.deepEqual(calls, [
    ["preference", "system"],
    ["scheme", "auto"],
    ["preference", "dark"],
    ["scheme", "dark"],
    "logout",
  ]);
});

void test("resizing to desktop closes a previously opened mobile navigation drawer", () => {
  const { harness, calls } = setup(true);
  harness.render({ children: "current screen" });
  harness.flushEffects();
  assert.deepEqual(calls, ["close"]);
});
