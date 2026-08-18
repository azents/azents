import assert from "node:assert/strict";
import test from "node:test";
import { isSupportedLocale, resolveLocaleFromHeader } from "./locale.ts";

await test("recognizes only supported locales", () => {
  assert.equal(isSupportedLocale("ko-KR"), true);
  assert.equal(isSupportedLocale("ko"), false);
  assert.equal(isSupportedLocale("de-DE"), false);
});

await test("resolves exact and language-only Accept-Language entries", () => {
  assert.equal(resolveLocaleFromHeader("fr-FR,ko;q=0.9"), "fr-FR");
  assert.equal(resolveLocaleFromHeader("de-DE,ja;q=0.8"), "ja-JP");
});

await test("ignores unsupported Accept-Language entries", () => {
  assert.equal(resolveLocaleFromHeader("de-DE,es;q=0.9"), null);
  assert.equal(resolveLocaleFromHeader(null), null);
});
