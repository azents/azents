import assert from "node:assert/strict";
import test from "node:test";
import {
  HookHarness,
  invoke,
} from "../../../shared/testing/hook-test-harness.ts";
import * as navigation from "./sessionPanel.ts";

const path = "/w/team/agents/agent/sessions/session";
function fixture(search: string): {
  hook: HookHarness;
  replaced: string[];
  navigate: (search: string) => void;
} {
  const hook = new HookHarness();
  let params = new URLSearchParams(search);
  const replaced: string[] = [];
  const router = {
    replace: (href: string): void => {
      replaced.push(href);
    },
  };
  hook.load(
    new URL("./useSessionPanelState.ts", import.meta.url),
    "useSessionPanelState",
    {
      react: hook.react,
      "@mantine/hooks": {
        useLocalStorage: (): unknown => hook.react.useState(0.55),
      },
      "next/navigation": {
        useRouter: () => router,
        usePathname: () => path,
        useSearchParams: () => params,
      },
      "./sessionPanel": navigation,
    },
    {},
  );
  return {
    hook,
    replaced,
    navigate: (search) => {
      params = new URLSearchParams(search);
    },
  };
}

void test("disabled Browser deep links resolve to files without mounting a Browser selection", () => {
  for (const mobile of [false, true]) {
    const { hook, replaced, navigate } = fixture(
      "page=browser&browserTaskId=t&browserPageId=p&browserIncarnation=i&other=kept",
    );
    let output = hook.render({ mobile, browserEnabled: false });
    assert.equal(output.activeView, "files");
    hook.flushEffects();
    assert.equal(replaced[0], `${path}?other=kept&page=files`);
    navigate("other=kept&page=files");
    output = hook.render({ mobile, browserEnabled: false });
    hook.flushEffects();
    assert.equal(output.activeView, "files");
    invoke(output.onSelect, "browser");
    assert.equal(hook.render().activeView, "files");
    hook.unmount();
  }
});

void test("disabling an active Browser retires selection synchronously and keeps unrelated query", () => {
  const { hook, replaced, navigate } = fixture(
    "page=browser&browserPageId=p&other=kept",
  );
  assert.equal(
    hook.render({ mobile: false, browserEnabled: true }).activeView,
    "browser",
  );
  hook.flushEffects();
  let output = hook.render({ mobile: false, browserEnabled: false });
  assert.equal(output.activeView, "files");
  hook.flushEffects();
  assert.equal(replaced.at(-1), `${path}?other=kept&page=files`);
  navigate("other=kept&page=files");
  hook.render();
  hook.flushEffects();
  output = hook.render({ mobile: false, browserEnabled: true });
  assert.equal(output.activeView, "files");
  hook.unmount();
});

void test("disabled Browser cannot reopen a pending or closed Browser selection", () => {
  const { hook, replaced, navigate } = fixture("other=kept");
  let output = hook.render({ mobile: true, browserEnabled: true });
  hook.flushEffects();
  invoke(output.onSelect, "browser");
  output = hook.render({ mobile: true, browserEnabled: false });
  assert.equal(output.activeView, "files");
  hook.flushEffects();
  invoke(output.onOpen);
  assert.equal(replaced.at(-1), `${path}?other=kept&page=files`);
  navigate("other=kept&page=browser");
  output = hook.render();
  assert.equal(output.activeView, "files");
  hook.flushEffects();
  assert.equal(replaced.at(-1), `${path}?other=kept&page=files`);
  hook.unmount();
});

void test("mobile Services and Context selection survives close and URL acknowledgement", () => {
  const { hook, replaced, navigate } = fixture("other=kept");
  let output = hook.render({ mobile: true, browserEnabled: false });
  hook.flushEffects();
  assert.equal(output.opened, false);
  invoke(output.onOpen);
  output = hook.render();
  assert.equal(output.opened, true);
  assert.equal(replaced.at(-1), `${path}?other=kept&page=files`);
  navigate("other=kept&page=files");
  hook.render();
  hook.flushEffects();
  for (const view of ["services", "context"]) {
    output = hook.render();
    invoke(output.onSelect, view);
    output = hook.render();
    assert.equal(output.opened, true);
    assert.equal(output.activeView, view);
    assert.equal(replaced.at(-1), `${path}?other=kept&page=${view}`);
    // The old URL remains visible until the router acknowledges the action.
    hook.flushEffects();
    assert.equal(hook.render().activeView, view);
    navigate(`other=kept&page=${view}`);
    hook.render();
    hook.flushEffects();
  }
  output = hook.render();
  invoke(output.onClose);
  assert.equal(hook.render().opened, false);
  assert.equal(replaced.at(-1), `${path}?other=kept`);
  navigate("other=kept");
  hook.render();
  hook.flushEffects();
  output = hook.render();
  invoke(output.onOpen);
  output = hook.render();
  assert.equal(output.opened, true);
  assert.equal(output.activeView, "context");
  assert.equal(replaced.at(-1), `${path}?other=kept&page=context`);
  navigate("other=kept&page=context");
  hook.render();
  hook.flushEffects();
  output = hook.render({ mobile: false, browserEnabled: false });
  hook.flushEffects();
  assert.equal(output.opened, true);
  assert.equal(output.activeView, "context");
  hook.unmount();
});
