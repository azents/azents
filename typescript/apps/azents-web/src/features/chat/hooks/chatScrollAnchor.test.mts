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

  assert.equal(
    restorePrependScrollTop(latestAnchor, {
      scrollHeight: 1_400,
      scrollTop: 30,
    }),
    430,
  );
});

void test("prepend restoration keeps the visible timeline item fixed", () => {
  let targetTop = 80;
  const target = {
    isConnected: true,
    getBoundingClientRect(): { top: number } {
      return { top: targetTop };
    },
  };
  const anchor = captureChatScrollAnchor(
    { scrollHeight: 1_000, scrollTop: 120 },
    target,
  );

  targetTop = 480;

  assert.equal(
    restorePrependScrollTop(anchor, {
      scrollHeight: 1_900,
      scrollTop: 280,
    }),
    680,
  );
});

void test("prepend restoration falls back to height delta when the item unmounts", () => {
  const target = {
    isConnected: false,
    getBoundingClientRect(): { top: number } {
      return { top: 80 };
    },
  };
  const anchor = captureChatScrollAnchor(
    { scrollHeight: 1_000, scrollTop: 120 },
    target,
  );

  assert.equal(
    restorePrependScrollTop(anchor, {
      scrollHeight: 1_400,
      scrollTop: 120,
    }),
    520,
  );
});
