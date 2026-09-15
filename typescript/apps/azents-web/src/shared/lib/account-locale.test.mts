import assert from "node:assert/strict";
import test from "node:test";
import {
  accountLocaleToSynchronize,
  isAccessTokenUsableForAccountLocale,
} from "./account-locale.ts";

const NOW = 1_789_430_400_000;

await test("uses a valid access token inside the proactive refresh window", () => {
  assert.equal(isAccessTokenUsableForAccountLocale(NOW + 60_000, NOW), true);
});

await test("rejects access tokens at or after their actual expiration", () => {
  assert.equal(isAccessTokenUsableForAccountLocale(NOW, NOW), false);
  assert.equal(isAccessTokenUsableForAccountLocale(NOW - 1, NOW), false);
});

await test("synchronizes a supported account locale only when it differs", () => {
  assert.equal(accountLocaleToSynchronize("ko-KR", "en-US"), "en-US");
  assert.equal(accountLocaleToSynchronize("en-US", "en-US"), null);
  assert.equal(accountLocaleToSynchronize("ko-KR", "de-DE"), null);
  assert.equal(accountLocaleToSynchronize("ko-KR", null), null);
});
