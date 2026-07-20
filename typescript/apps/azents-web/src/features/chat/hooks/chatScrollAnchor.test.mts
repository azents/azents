import assert from "node:assert/strict";
import test from "node:test";

import {
  captureChatScrollAnchor,
  restorePrependScrollTop,
} from "./chatScrollAnchor.ts";

void test("prepend restoration retains the latest user scroll position", () => {
  const initialAnchor = captureChatScrollAnchor({
    scrollHeight: 1_000,
    scrollTop: 120,
  });
  const latestAnchor = captureChatScrollAnchor({
    scrollHeight: initialAnchor.scrollHeight,
    scrollTop: 30,
  });

  assert.equal(restorePrependScrollTop(latestAnchor, 1_400), 430);
});
