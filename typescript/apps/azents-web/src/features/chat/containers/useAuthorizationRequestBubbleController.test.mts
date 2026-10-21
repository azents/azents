import assert from "node:assert/strict";
import test from "node:test";
import {
  HookHarness,
  invoke,
} from "../../../shared/testing/hook-test-harness.ts";

void test("authorization popup opens before URL receipt and accepts only same-origin successful callback records", async () => {
  const harness = new HookHarness();
  let callback: unknown;
  let authorized = 0;
  const opened: unknown[][] = [];
  let closed = false;
  const popup = {
    closed: false,
    location: { href: "" },
    close: (): void => {
      closed = true;
    },
  };
  harness.load(
    new URL("./useAuthorizationRequestBubbleController.tsx", import.meta.url),
    "useAuthorizationRequestBubbleController",
    {
      react: harness.react,
      "next-intl": {
        useTranslations: (): ((key: string) => string) => (key) => key,
      },
      "@mantine/hooks": {
        useWindowEvent: (name: string, listener: unknown): void => {
          assert.equal(name, "message");
          callback = listener;
        },
      },
      "@/shared/lib/unknown-value": {
        isRecord: (value: unknown): boolean =>
          value != null && typeof value === "object" && !Array.isArray(value),
      },
    },
    {
      location: { origin: "https://azents.example" },
      open: (...args: unknown[]): typeof popup => {
        opened.push(args);
        return popup;
      },
    },
  );
  const receipt = harness.nativeDeferred();
  const view = harness.render({
    toolkitName: "Calendar",
    authorizationUrl: "",
    getAuthorizationUrl: (): PromiseLike<unknown> => receipt.promise,
    onAuthorized: (): void => {
      authorized += 1;
    },
  });
  const action = invoke(view.handleClick);
  assert.equal(opened.length, 1);
  assert.equal(opened[0]?.[0], "about:blank");
  assert.equal(harness.render().isOpening, true);
  receipt.resolve("https://provider.example/oauth");
  await action;
  assert.equal(popup.location.href, "https://provider.example/oauth");
  assert.equal(closed, false);
  assert.equal(harness.render().isOpening, false);
  for (const event of [
    {
      origin: "https://foreign.example",
      data: { type: "azents-oauth-callback", success: true },
    },
    { origin: "https://azents.example", data: null },
    {
      origin: "https://azents.example",
      data: [{ type: "azents-oauth-callback", success: true }],
    },
    {
      origin: "https://azents.example",
      data: { type: "other", success: true },
    },
    {
      origin: "https://azents.example",
      data: { type: "azents-oauth-callback", success: false },
    },
    {
      origin: "https://azents.example",
      data: { type: "azents-oauth-callback", success: "true" },
    },
  ]) {
    invoke(callback, event);
  }
  assert.equal(authorized, 0);
  invoke(callback, {
    origin: "https://azents.example",
    data: { type: "azents-oauth-callback", success: true },
  });
  assert.equal(authorized, 1);
});

void test("authorization URL rejection closes the early popup and clears opening state", async () => {
  const harness = new HookHarness();
  let closed = 0;
  harness.load(
    new URL("./useAuthorizationRequestBubbleController.tsx", import.meta.url),
    "useAuthorizationRequestBubbleController",
    {
      react: harness.react,
      "next-intl": {
        useTranslations: (): ((key: string) => string) => (key) => key,
      },
      "@mantine/hooks": { useWindowEvent: (): void => {} },
      "@/shared/lib/unknown-value": { isRecord: (): boolean => false },
    },
    {
      open: (): object => ({
        close: (): void => {
          closed += 1;
        },
      }),
    },
  );
  const view = harness.render({
    toolkitName: "Calendar",
    authorizationUrl: "",
    getAuthorizationUrl: (): Promise<never> =>
      Promise.reject(new Error("Provider rejected.")),
    onAuthorized: (): void => {},
  });
  await invoke(view.handleClick);
  assert.equal(closed, 1);
  assert.equal(harness.render().isOpening, false);
});
