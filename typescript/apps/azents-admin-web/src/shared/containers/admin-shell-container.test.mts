import assert from "node:assert/strict";
import { test } from "node:test";
import { adminNavigation } from "../lib/admin-navigation.ts";
import { getPublicRoutePath } from "../lib/auth-policy.ts";
import { HookHarness, invoke, record } from "../testing/hook-harness.ts";

function setup(
  desktop: boolean,
  initialSection: string | null = "audit",
): {
  harness: HookHarness;
  calls: unknown[];
  selectSection: (value: string | null) => void;
} {
  const harness = new HookHarness();
  const calls: unknown[] = [];
  let sectionValue = initialSection;
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
        useSearchParams: () => ({
          get: (key: string): string | null =>
            key === "section" ? sectionValue : null,
        }),
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
  return {
    harness,
    calls,
    selectSection: (value): void => {
      sectionValue = value;
    },
  };
}

void test("shared shell projects the current query and preserves theme and logout collaborators", () => {
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

void test("query-only Next navigation updates the shell location without a remount or browser event", () => {
  const { harness, selectSection } = setup(false, "github");
  assert.equal(
    record(harness.render({ children: "current screen" }).location).label,
    "GitHub",
  );
  selectSection("audit");
  assert.equal(
    record(harness.render({ children: "current screen" }).location).label,
    "Audit log",
  );
});

void test("missing query selects the default screen without accessing window", () => {
  const { harness } = setup(false, null);
  assert.equal(
    record(harness.render({ children: "current screen" }).location).label,
    "Google",
  );
});
