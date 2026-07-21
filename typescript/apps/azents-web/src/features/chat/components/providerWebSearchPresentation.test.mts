import assert from "node:assert/strict";
import test from "node:test";
import { providerWebSearchPresentation } from "./providerWebSearchPresentation.ts";
import type { ProviderToolCall } from "../types.ts";

function webSearchCall(
  overrides: Partial<ProviderToolCall> = {},
): ProviderToolCall {
  return {
    id: "search-1",
    name: "web_search",
    arguments: '{"query":"Azents"}',
    status: "completed",
    references: [
      {
        kind: "url",
        uri: "https://example.com/results",
        title: "Azents results",
        excerpt: "A concise result excerpt.",
        metadata: {},
      },
    ],
    ...overrides,
  };
}

void test("projects structured web search references", () => {
  assert.deepEqual(providerWebSearchPresentation(webSearchCall()), {
    query: "Azents",
    results: [
      {
        uri: "https://example.com/results",
        title: "Azents results",
        excerpt: "A concise result excerpt.",
      },
    ],
    summary: null,
  });
});

void test("keeps web search identity before valid references arrive", () => {
  assert.deepEqual(
    providerWebSearchPresentation(webSearchCall({ references: [] })),
    { query: "Azents", results: [], summary: null },
  );
  assert.equal(
    providerWebSearchPresentation(webSearchCall({ name: "file_search" })),
    null,
  );
});
