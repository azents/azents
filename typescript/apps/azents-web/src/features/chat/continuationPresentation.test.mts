import assert from "node:assert/strict";
import test from "node:test";
import {
  continuationMetadata,
  continuationPresentation,
} from "./continuationPresentation.ts";
import type { ChatMessage } from "./types";

function continuationMessage(
  metadata: Record<string, string> = {},
): ChatMessage {
  return {
    id: "continuation-1",
    role: "goal_continuation",
    content: null,
    createdAt: "2026-07-23T00:00:00.000Z",
    metadata,
  };
}

void test("preserves string continuation metadata", () => {
  assert.deepEqual(
    continuationMetadata({
      source: "external_channel",
      active_bindings: "binding-1",
      ignored: 1,
    }),
    {
      source: "external_channel",
      active_bindings: "binding-1",
    },
  );
});

void test("classifies external Channel Work continuation", () => {
  assert.deepEqual(
    continuationPresentation(
      continuationMessage({
        source: "external_channel",
        active_bindings: "binding-1",
      }),
    ),
    {
      source: "external_channel",
      icon: "channel",
      labelKey: "externalChannelContinuationIndicator",
    },
  );
});

void test("keeps ordinary continuation in the Goal presentation", () => {
  assert.deepEqual(continuationPresentation(continuationMessage()), {
    source: "goal",
    icon: "target",
    labelKey: "goalContinuationIndicator",
  });
});
