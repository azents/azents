import assert from "node:assert/strict";
import test from "node:test";
import { HookHarness, invoke } from "../testing/hook-test-harness.ts";

void test("color mode preserves the SSR snapshot, follows system changes, and samples current browser state on selection", () => {
  const harness = new HookHarness();
  let dark = true;
  const cookies: string[] = [];
  const document = {
    set cookie(value: string) {
      cookies.push(value);
    },
  };
  harness.load(
    new URL("./color-mode.tsx", import.meta.url),
    "ColorModeProvider",
    {
      react: {
        ...harness.react,
        createContext: (): object => ({ Provider: "provider" }),
      },
      "react/jsx-runtime": {
        jsx: (_type: unknown, props: { value: unknown }): unknown =>
          props.value,
      },
      "@mantine/hooks": {
        useColorScheme: (): string => (dark ? "dark" : "light"),
      },
    },
    { matchMedia: (): { matches: boolean } => ({ matches: dark }) },
    document,
  );
  let view = harness.render({
    initialPreference: "system",
    initialResolvedMode: "light",
    children: null,
  });
  assert.equal(view.mode, "light");
  harness.flushEffects();
  view = harness.render();
  assert.equal(view.mode, "dark");
  invoke(view.setColorMode, "light");
  view = harness.render();
  harness.flushEffects();
  assert.equal(harness.render().mode, "light");
  dark = false;
  view = harness.render();
  harness.flushEffects();
  assert.equal(harness.render().mode, "light");
  dark = true;
  // Selection uses current browser state even before the subscription rerenders.
  invoke(view.setColorMode, "system");
  view = harness.render();
  assert.equal(view.mode, "dark");
  harness.flushEffects();
  dark = false;
  harness.render();
  harness.flushEffects();
  assert.equal(harness.render().mode, "light");
  assert.ok(
    cookies.includes(
      "color-mode-preference=system; expires=Thu, 14 Oct 2027 00:00:00 GMT; path=/; SameSite=Lax",
    ),
  );
  assert.ok(
    cookies.includes(
      "color-mode-resolved=dark; expires=Thu, 14 Oct 2027 00:00:00 GMT; path=/; SameSite=Lax",
    ),
  );
});
