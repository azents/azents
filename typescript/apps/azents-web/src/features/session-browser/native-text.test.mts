import assert from "node:assert/strict";
import test from "node:test";
import { browserNativeTextChange } from "./native-text.ts";

void test("iOS Korean ordinary insert/delete updates preserve composed syllables", () => {
  let remote = "";
  let previous = "";
  for (const next of [
    "ㅇ",
    "",
    "아",
    "",
    "안",
    "안ㄴ",
    "안",
    "안녀",
    "안",
    "안녕",
  ]) {
    const { remove, insert } = browserNativeTextChange(previous, next);
    const parts = [
      ...new Intl.Segmenter("en", { granularity: "grapheme" }).segment(remote),
    ].map((part) => part.segment);
    remote = parts.slice(0, parts.length - remove).join("") + insert;
    assert.equal(remote, next);
    previous = next;
  }
  assert.equal(remote, "안녕");
});

void test("native replacement and deletion count complete graphemes", () => {
  assert.deepEqual(browserNativeTextChange("a👨‍👩‍👧‍👦", "ab"), {
    remove: 1,
    insert: "b",
  });
  assert.deepEqual(browserNativeTextChange("abc", "abc"), {
    remove: 0,
    insert: "",
  });
  assert.deepEqual(browserNativeTextChange("한글", "한"), {
    remove: 1,
    insert: "",
  });
});
