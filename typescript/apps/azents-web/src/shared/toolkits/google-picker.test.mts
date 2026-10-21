import assert from "node:assert/strict";
import { test } from "node:test";
import {
  deferred,
  HookHarness,
  invoke,
  object,
} from "../testing/hook-test-harness.ts";
import type { GooglePickerApi } from "./google-picker.ts";

const receipt = {
  access_token: "TRANSIENT-TEST-TOKEN",
  api_key: "browser-key",
  app_id: "1234",
  expires_at: "2026-10-14T00:01:00Z",
};
interface Observation {
  token: string;
  key: string;
  appId: string;
  origin: string;
  disposed: number;
  visible: boolean;
  callback: (value: unknown) => void;
}
function sdkFixture(): { observation: Observation; api: GooglePickerApi } {
  const observation = {
    token: "",
    key: "",
    appId: "",
    origin: "",
    disposed: 0,
    visible: false,
    callback: (value: unknown): void => {
      void value;
    },
  };
  class Builder {
    setOAuthToken(value: string): Builder {
      observation.token = value;
      return this;
    }
    setDeveloperKey(value: string): Builder {
      observation.key = value;
      return this;
    }
    setAppId(value: string): Builder {
      observation.appId = value;
      return this;
    }
    setOrigin(value: string): Builder {
      observation.origin = value;
      return this;
    }
    addView(value: string): Builder {
      assert.equal(value, "docs");
      return this;
    }
    setCallback(callback: (value: unknown) => void): Builder {
      observation.callback = callback;
      return this;
    }
    build(): { setVisible: (visible: boolean) => void; dispose: () => void } {
      return {
        setVisible: (visible) => {
          observation.visible = visible;
        },
        dispose: () => {
          observation.disposed += 1;
          observation.token = "";
        },
      };
    }
  }
  return {
    observation,
    api: { PickerBuilder: Builder, ViewId: { DOCS: "docs" } },
  };
}
for (const action of ["picked", "cancel", "expired", "close"]) {
  void test(`official Picker lifecycle disposes transient credentials on ${action}`, () => {
    const h = new HookHarness();
    const sdk = sdkFixture();
    const timer = { expire: (): void => {}, cancelled: false, ms: 0 };
    const open = h.load(
      new URL("./google-picker.ts", import.meta.url),
      "openGooglePicker",
      {},
      { location: { origin: "https://web.example.test" } },
      {},
      {
        setTimeout: (callback: () => void, ms: number) => {
          timer.expire = callback;
          timer.ms = ms;
          return 1;
        },
        clearTimeout: () => {
          timer.cancelled = true;
        },
      },
    );
    const results: unknown[] = [];
    const handle = object(
      invoke(open, sdk.api, receipt, (result: unknown) => results.push(result)),
    );
    assert.equal(sdk.observation.token, receipt.access_token);
    assert.equal(sdk.observation.appId, "1234");
    assert.equal(sdk.observation.origin, "https://web.example.test");
    assert.equal(timer.ms, 60000);
    assert.equal(sdk.observation.visible, true);
    if (action === "expired") {
      timer.expire();
    } else if (action === "close") {
      invoke(handle.close);
    } else {
      sdk.observation.callback({
        action,
        docs: [{ id: "untrusted-id", url: "https://untrusted.example/file" }],
      });
    }
    assert.equal(sdk.observation.token, "");
    assert.equal(sdk.observation.visible, false);
    assert.equal(sdk.observation.disposed, 1);
    assert.equal(timer.cancelled, true);
    invoke(handle.close);
    sdk.observation.callback({ action: "picked", docs: [{ id: "late-id" }] });
    assert.equal(sdk.observation.disposed, 1);
    assert.equal(results.length, action === "close" ? 0 : 1);
    if (action === "picked") {
      assert.deepEqual(JSON.parse(JSON.stringify(results)), [
        { type: "SELECTED", count: 1 },
      ]);
    }
    assert.equal(JSON.stringify(results).includes("untrusted"), false);
    assert.equal(JSON.stringify(results).includes(receipt.access_token), false);
  });
}
void test("Picker rejects expired receipts before constructing any iframe", () => {
  const h = new HookHarness();
  const open = h.load(
    new URL("./google-picker.ts", import.meta.url),
    "openGooglePicker",
    {},
    {},
  );
  const sdk = sdkFixture();
  assert.throws(
    () =>
      invoke(
        open,
        sdk.api,
        { ...receipt, expires_at: "2026-10-13T00:00:00Z" },
        () => {},
      ),
    /expired/,
  );
  assert.equal(sdk.observation.token, "");
});

void test("Picker SDK cache recovers from synchronous SDK load failure", async () => {
  const h = new HookHarness();
  const sdk = sdkFixture();
  let failed = true;
  let loads = 0;
  let cleared = 0;
  const loader = h.load(
    new URL("./google-picker.ts", import.meta.url),
    "loadGooglePicker",
    {},
    {
      google: { picker: sdk.api },
      gapi: {
        load: (
          _name: string,
          options: { onerror: () => void; callback: () => void },
        ) => {
          loads += 1;
          if (failed) {
            options.onerror();
          } else {
            options.callback();
          }
        },
      },
    },
    {},
    {
      setTimeout: () => 1,
      clearTimeout: () => {
        cleared += 1;
      },
    },
  );
  await assert.rejects(async () => {
    await invoke(loader);
  }, /unavailable/);
  failed = false;
  assert.equal(await invoke(loader), sdk.api);
  assert.equal(loads, 2);
  assert.equal(cleared, 2);
  assert.equal(invoke(loader), invoke(loader));
});

void test("Picker bounds a stalled official script load and removes only its own script", async () => {
  const h = new HookHarness();
  let expire = (): void => {};
  let removed = 0;
  let appended = 0;
  const loader = h.load(
    new URL("./google-picker.ts", import.meta.url),
    "loadGooglePicker",
    {},
    {},
    {
      createElement: () => ({
        remove: () => {
          removed += 1;
        },
      }),
      head: {
        append: () => {
          appended += 1;
        },
      },
    },
    {
      setTimeout: (callback: () => void, ms: number) => {
        assert.equal(ms, 15000);
        expire = callback;
        return 1;
      },
      clearTimeout: () => {},
    },
  );
  const pending = invoke(loader);
  expire();
  await assert.rejects(async () => {
    await pending;
  }, /unavailable/);
  assert.equal(removed, 1);
  assert.equal(appended, 1);
});
for (const boundary of [
  "unmount",
  "connection_changed",
  "disabled",
  "explicit_close",
]) {
  void test(`Picker hook fences in-flight credentials after ${boundary}`, async () => {
    const h = new HookHarness();
    const provider = deferred<unknown>();
    const requested = deferred<void>();
    let opens = 0;
    const props = {
      enabled: true,
      contextKey: "connection:7",
      issue: () => {
        requested.resolve();
        return provider.promise;
      },
      unavailableMessage: "Unavailable",
      expiredMessage: "Expired",
    };
    h.load(
      new URL("./containers/useGooglePickerContainer.ts", import.meta.url),
      "useGooglePickerContainer",
      {
        react: h.react,
        "../google-picker": {
          loadGooglePicker: () => Promise.resolve({}),
          openGooglePicker: () => {
            opens += 1;
            return { close: () => {} };
          },
        },
      },
      {},
    );
    let result = h.render(props);
    h.flushEffects();
    result = h.render();
    const operation = invoke(result.onOpenPicker);
    await requested.promise;
    if (boundary === "unmount") {
      h.unmount();
    } else if (boundary === "explicit_close") {
      invoke(result.onClosePicker);
    } else {
      h.render({
        ...props,
        ...(boundary === "disabled"
          ? { enabled: false }
          : { contextKey: "connection:8" }),
      });
      h.flushEffects();
    }
    provider.resolve(receipt);
    await operation;
    assert.equal(opens, 0);
    assert.equal(
      JSON.stringify(h.render()).includes(receipt.access_token),
      false,
    );
  });
}
void test("Picker hook clears the displayed SDK instance on unmount", async () => {
  const h = new HookHarness();
  const opened = deferred<void>();
  let closes = 0;
  h.load(
    new URL("./containers/useGooglePickerContainer.ts", import.meta.url),
    "useGooglePickerContainer",
    {
      react: h.react,
      "../google-picker": {
        loadGooglePicker: () => Promise.resolve({}),
        openGooglePicker: () => {
          opened.resolve();
          return {
            close: () => {
              closes += 1;
            },
          };
        },
      },
    },
    {},
  );
  let result = h.render({
    enabled: true,
    contextKey: "connection:7",
    issue: () => Promise.resolve(receipt),
    unavailableMessage: "Unavailable",
    expiredMessage: "Expired",
  });
  h.flushEffects();
  result = h.render();
  invoke(result.onOpenPicker);
  await opened.promise;
  assert.equal(object(h.render().picker).type, "OPEN");
  h.unmount();
  assert.equal(closes, 1);
});
