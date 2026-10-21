import assert from "node:assert/strict";
import { test } from "node:test";
import { projectSessionContextUsage } from "./session-context-usage.ts";
void test("usage projection preserves numeric acceptance and opaque source identity", () => {
  const extension = { opaque: true };
  const source = {
    total_tokens: 0,
    prompt_tokens: -1,
    completion_tokens: 1.5,
    reasoning_tokens: Number.NaN,
    cached_tokens: Number.POSITIVE_INFINITY,
    cache_creation_tokens: 10,
    extension,
  };
  assert.deepEqual(projectSessionContextUsage(source), {
    totalTokens: 0,
    promptTokens: -1,
    completionTokens: 1.5,
    reasoningTokens: Number.NaN,
    cachedTokens: Number.POSITIVE_INFINITY,
    cacheCreationTokens: 10,
  });
  assert.equal(source.extension, extension);
});
void test("missing and malformed usage counters retain unavailable presentation", () => {
  const unavailable = {
    totalTokens: null,
    promptTokens: null,
    completionTokens: null,
    reasoningTokens: null,
    cachedTokens: null,
    cacheCreationTokens: null,
  };
  for (const source of [
    null,
    void 0,
    {},
    {
      total_tokens: "1",
      prompt_tokens: false,
      completion_tokens: null,
      reasoning_tokens: [],
      cached_tokens: {},
      cache_creation_tokens: true,
    },
  ]) {
    assert.deepEqual(projectSessionContextUsage(source), unavailable);
  }
});
