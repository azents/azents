import assert from "node:assert/strict";
import { test } from "node:test";
import { HookHarness } from "../testing/hook-harness.ts";
for (const desktop of [true, false]) {
  void test(`master detail preserves props and desktop SSR default with resolved desktop=${desktop}`, () => {
    const calls: unknown[] = [];
    const harness = new HookHarness();
    harness.load(
      new URL("./useMasterDetailLayoutContainer.ts", import.meta.url),
      "useMasterDetailLayoutContainer",
      {
        "@mantine/hooks": {
          useMediaQuery: (...args: unknown[]): boolean => {
            calls.push(args);
            return desktop;
          },
        },
      },
    );
    const props = {
      master: "master",
      detail: "detail",
      detailOpen: true,
      onDetailClose: (): void => {},
      columns: "1fr 2fr",
      style: { height: "90%" },
    };
    const output = harness.render(props);
    assert.deepEqual(calls, [["(min-width: 62em)", true]]);
    assert.equal(output.isDesktop, desktop);
    for (const [key, value] of Object.entries(props)) {
      assert.equal(output[key], value);
    }
  });
}
