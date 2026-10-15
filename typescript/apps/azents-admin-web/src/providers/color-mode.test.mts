import assert from "node:assert/strict";
import { test } from "node:test";
import { HookHarness, invoke, record } from "../shared/testing/hook-harness.ts";

function setup(
  initialSystemMode: "light" | "dark",
  server = false,
): {
  harness: HookHarness;
  cookies: string[];
  observations: string[];
  setSystemMode: (mode: "light" | "dark") => void;
} {
  const harness = new HookHarness();
  const cookies: string[] = [];
  const observations: string[] = [];
  let systemMode = initialSystemMode;
  const document = {
    set cookie(value: string) {
      cookies.push(value);
    },
  };
  const jsx = (_type: unknown, props: unknown): unknown => props;
  harness.load(
    new URL("./color-mode.tsx", import.meta.url),
    "ColorModeProvider",
    {
      react: harness.react,
      "react/jsx-runtime": { jsx },
      "@mantine/hooks": {
        useColorScheme: (initial: string): string => {
          observations.push(initial);
          return systemMode;
        },
      },
    },
    server ? {} : { document },
  );
  return {
    harness,
    cookies,
    observations,
    setSystemMode: (value) => {
      systemMode = value;
    },
  };
}

function value(output: Record<string, unknown>): Record<string, unknown> {
  return record(output.value);
}

void test("color provider retains initial SSR values without observing its own browser API", () => {
  const { harness, cookies, observations } = setup("dark", true);
  const output = harness.render({
    initialPreference: "system",
    initialResolvedMode: "light",
    children: "content",
  });
  assert.equal(value(output).mode, "light");
  assert.equal(value(output).preference, "system");
  assert.deepEqual(observations, ["light"]);
  assert.deepEqual(cookies, []);
  assert.equal(output.children, "content");
});

void test("system preference follows the Mantine observation and preserves resolved cookie policy", () => {
  const { harness, cookies, setSystemMode } = setup("dark");
  const props = { initialPreference: "system", initialResolvedMode: "light" };
  harness.render(props);
  harness.flushEffects();
  assert.equal(value(harness.render(props)).mode, "dark");
  assert.equal(cookies.length, 1);
  assert.match(
    cookies[0] ?? "",
    /^color-mode-resolved=dark; expires=.*; path=\/; SameSite=Lax$/,
  );
  setSystemMode("light");
  harness.render(props);
  harness.flushEffects();
  assert.equal(value(harness.render(props)).mode, "light");
  assert.match(cookies.at(-1) ?? "", /^color-mode-resolved=light;/);
});

void test("explicit selection ignores system changes and switching back uses the latest observation", () => {
  const { harness, cookies, setSystemMode } = setup("light");
  const props = { initialPreference: "dark", initialResolvedMode: "dark" };
  let output = harness.render(props);
  harness.flushEffects();
  assert.equal(cookies.length, 0);
  assert.equal(value(output).mode, "dark");
  invoke(value(output).setColorMode, "light");
  output = harness.render(props);
  assert.equal(value(output).mode, "light");
  assert.equal(value(output).preference, "light");
  assert.match(
    cookies[0] ?? "",
    /^color-mode-preference=light; expires=.*; path=\/; SameSite=Lax$/,
  );
  setSystemMode("dark");
  output = harness.render(props);
  harness.flushEffects();
  assert.equal(value(harness.render(props)).mode, "light");
  invoke(value(output).setColorMode, "system");
  output = harness.render(props);
  assert.equal(value(output).preference, "system");
  assert.equal(value(output).mode, "dark");
  assert.match(cookies.at(-2) ?? "", /^color-mode-preference=system;/);
  assert.match(cookies.at(-1) ?? "", /^color-mode-resolved=dark;/);
});
