import assert from "node:assert/strict";
import test from "node:test";

import { hasLiveModelProgress } from "./liveRetryVisibility.ts";
import type { ChatMessage } from "../types.ts";

const createdAt = "2026-07-17T06:52:21.000Z";

void test("live provider-tool progress supersedes the retry card", () => {
  const messages = [
    {
      id: "image-generation-progress",
      role: "assistant",
      content: null,
      createdAt,
      status: "partial",
      providerToolCalls: [
        {
          id: "image-generation-call",
          callId: "image-generation-call",
          name: "image_generation",
          arguments: "{}",
          status: "running",
        },
      ],
    },
  ] satisfies ChatMessage[];

  assert.equal(hasLiveModelProgress(messages), true);
});

void test("live agent mailbox input does not suppress an active retry card", () => {
  const messages = [
    {
      id: "agent-mailbox-input",
      role: "user",
      content: "A subagent sent an update.",
      createdAt,
      status: "partial",
    },
  ] satisfies ChatMessage[];

  assert.equal(hasLiveModelProgress(messages), false);
});

void test("durable output does not suppress an active retry card", () => {
  const messages = [
    {
      id: "previous-response",
      role: "assistant",
      content: "Previous durable output",
      createdAt,
      status: "complete",
    },
  ] satisfies ChatMessage[];

  assert.equal(hasLiveModelProgress(messages), false);
});
