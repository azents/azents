import assert from "node:assert/strict";
import test from "node:test";

import {
  providerToolActivityLabel,
  providerToolDisplayName,
} from "../components/providerToolCallPresentation.ts";
import {
  applyProviderToolCallItem,
  providerToolCallStatusFromPayload,
} from "./providerToolCallProjection.ts";
import type { ProviderToolCall } from "../types.ts";

void test("canonical status wins over live provenance", () => {
  assert.equal(
    providerToolCallStatusFromPayload("completed", "partial"),
    "completed",
  );
  assert.equal(
    providerToolCallStatusFromPayload("failed", "partial"),
    "failed",
  );
  assert.equal(providerToolCallStatusFromPayload(null, "partial"), "running");
  assert.equal(
    providerToolCallStatusFromPayload("in_progress", "complete"),
    "unknown",
  );
});

void test("durable provider call replaces its live semantic identity", () => {
  const liveCall: ProviderToolCall = {
    id: "search-1",
    callId: "search-1",
    name: "web_search",
    arguments: "",
    status: "running",
  };
  const liveMessages = applyProviderToolCallItem(
    [],
    liveCall,
    "live-event-1",
    "2026-07-16T12:00:00Z",
    "partial",
  );
  const durableMessages = applyProviderToolCallItem(
    liveMessages,
    { ...liveCall, status: "completed" },
    "durable-event-1",
    "2026-07-16T12:00:01Z",
    "complete",
  );

  assert.equal(durableMessages.length, 1);
  const durableMessage = durableMessages[0];
  assert.ok(durableMessage);
  assert.equal(durableMessage.id, "durable-event-1");
  const durableToolCall = durableMessage.providerToolCalls?.[0];
  assert.ok(durableToolCall);
  assert.equal(durableToolCall.status, "completed");
});

void test("multiple provider calls keep independent semantic identities", () => {
  const firstCall: ProviderToolCall = {
    id: "search-1",
    callId: "search-1",
    name: "web_search",
    arguments: "",
    status: "running",
  };
  const secondCall: ProviderToolCall = {
    id: "code-1",
    callId: "code-1",
    name: "code_interpreter",
    arguments: "",
    status: "running",
  };

  const runningMessages = applyProviderToolCallItem(
    applyProviderToolCallItem(
      [],
      firstCall,
      "live-search",
      "2026-07-16T12:00:00Z",
      "partial",
    ),
    secondCall,
    "live-code",
    "2026-07-16T12:00:01Z",
    "partial",
  );
  const updatedMessages = applyProviderToolCallItem(
    runningMessages,
    { ...firstCall, status: "completed" },
    "durable-search",
    "2026-07-16T12:00:02Z",
    "complete",
  );

  assert.equal(updatedMessages.length, 2);
  assert.equal(updatedMessages[0]?.id, "durable-search");
  assert.equal(updatedMessages[1]?.id, "live-code");
});

void test("provider tool presentation uses semantic names instead of providers", () => {
  const call: ProviderToolCall = {
    id: "search-1",
    callId: "search-1",
    name: "web_search",
    arguments: "",
    status: "running",
  };

  assert.equal(providerToolDisplayName(call.name), "Web search");
  assert.equal(providerToolActivityLabel(call), "Searching the web");
  assert.equal(providerToolDisplayName("custom_retrieval"), "Custom retrieval");
});
