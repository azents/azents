import assert from "node:assert/strict";
import test from "node:test";

import {
  providerToolActivityLabel,
  providerToolDisplayName,
} from "../components/providerToolCallPresentation.ts";
import {
  applyProviderToolCallItem,
  providerToolCallFromPayload,
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
    providerToolCallStatusFromPayload("cancelled", "complete"),
    "failed",
  );
  assert.equal(
    providerToolCallStatusFromPayload("interrupted", "complete"),
    "failed",
  );
  assert.equal(
    providerToolCallStatusFromPayload("in_progress", "complete"),
    "unknown",
  );
});

void test("provider call projects text and one attachment while hiding file parts", () => {
  const payload = {
    call_id: "image-1",
    name: "image_generation",
    status: "completed",
    semantic: {
      input: '{"prompt":"A reliable timeline"}',
      output: [
        { type: "text", text: "Generated one image." },
        {
          type: "file",
          model_file_id: "model-file-1",
          media_type: "image/jpeg",
          name: "generated.jpg",
          size: 123,
          kind: "image",
        },
        {
          type: "attachment",
          attachment_id: "attachment-1",
          uri: "exchange://generated-image",
          media_type: "image/png",
          name: "generated.png",
          size: 68,
          availability: "available",
        },
        {
          type: "attachment",
          attachment_id: "attachment-1",
          uri: "exchange://generated-image",
          media_type: "image/png",
          name: "generated.png",
          size: 68,
          availability: "available",
        },
      ],
      references: [
        {
          kind: "url",
          uri: "https://example.com/source",
          title: "Source",
          excerpt: null,
          metadata: {},
        },
      ],
    },
  };

  const projected = providerToolCallFromPayload(payload, "complete");

  assert.ok(projected);
  assert.equal(projected.arguments, payload.semantic.input);
  assert.equal(
    projected.output,
    "Generated one image.\nReferences:\n" +
      "- url: https://example.com/source\n  Title: Source",
  );
  assert.equal(projected.output.includes("model-file-1"), false);
  assert.equal(projected.semanticOutput, "Generated one image.");
  assert.deepEqual(projected.references, [
    {
      kind: "url",
      uri: "https://example.com/source",
      title: "Source",
      excerpt: null,
      metadata: {},
    },
  ]);
  assert.deepEqual(projected.attachments, [
    {
      attachmentId: "attachment-1",
      uri: "exchange://generated-image",
      mediaType: "image/png",
      name: "generated.png",
      size: 68,
      textPreview: null,
      availability: "available",
      previewTitle: null,
      previewThumbnailUri: null,
      previewThumbnailMediaType: null,
      previewThumbnailWidth: null,
      previewThumbnailHeight: null,
      previewGeneratedAt: null,
    },
  ]);
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
