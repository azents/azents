import type { ChatMessage, FileAttachment, ProviderToolCall } from "../types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringField(
  record: Record<string, unknown>,
  key: string,
): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

function attachmentFromRecord(
  record: Record<string, unknown>,
): FileAttachment | null {
  const uri = stringField(record, "uri");
  const mediaType = stringField(record, "media_type");
  const name = stringField(record, "name");
  if (uri === null || mediaType === null || name === null) {
    return null;
  }
  const size = record.size;
  return {
    attachmentId: stringField(record, "attachment_id"),
    uri,
    mediaType,
    name,
    ...(typeof size === "number" ? { size } : {}),
    textPreview: stringField(record, "text_preview"),
    availability:
      record.availability === "expired" || record.availability === "unavailable"
        ? record.availability
        : "available",
    previewTitle: stringField(record, "preview_title"),
    previewThumbnailUri: stringField(record, "preview_thumbnail_uri"),
    previewThumbnailMediaType: stringField(
      record,
      "preview_thumbnail_media_type",
    ),
    previewThumbnailWidth:
      typeof record.preview_thumbnail_width === "number"
        ? record.preview_thumbnail_width
        : null,
    previewThumbnailHeight:
      typeof record.preview_thumbnail_height === "number"
        ? record.preview_thumbnail_height
        : null,
    previewGeneratedAt: stringField(record, "preview_generated_at"),
  };
}

function providerToolReferenceText(value: unknown): string | null {
  if (!isRecord(value)) {
    return null;
  }
  const kind = stringField(value, "kind") ?? "other";
  const uri = stringField(value, "uri");
  const title = stringField(value, "title");
  const excerpt = stringField(value, "excerpt");
  const primary = uri ?? title;
  const lines = [`- ${kind}${primary === null ? "" : `: ${primary}`}`];
  if (uri !== null && title !== null) {
    lines.push(`  Title: ${title}`);
  }
  if (excerpt !== null) {
    lines.push("  Excerpt:");
    lines.push(...excerpt.split("\n").map((line) => `    ${line}`));
  }
  if (isRecord(value.metadata)) {
    const metadata = Object.fromEntries(
      Object.entries(value.metadata)
        .filter(
          (entry): entry is [string, string] => typeof entry[1] === "string",
        )
        .sort(([left], [right]) => left.localeCompare(right)),
    );
    if (Object.keys(metadata).length > 0) {
      lines.push(`  Metadata: ${JSON.stringify(metadata)}`);
    }
  }
  return lines.join("\n");
}

function providerToolOutputText(
  output: unknown,
  references: unknown[],
): string {
  const sections: string[] = [];
  if (typeof output === "string") {
    if (output.length > 0) {
      sections.push(output);
    }
  } else if (Array.isArray(output)) {
    const outputText = output
      .flatMap((part) => {
        if (!isRecord(part) || part.type !== "text") {
          return [];
        }
        const text = stringField(part, "text");
        return text === null ? [] : [text];
      })
      .join("\n");
    if (outputText.length > 0) {
      sections.push(outputText);
    }
  }
  const renderedReferences = references.flatMap((reference) => {
    const rendered = providerToolReferenceText(reference);
    return rendered === null ? [] : [rendered];
  });
  if (renderedReferences.length > 0) {
    sections.push(`References:\n${renderedReferences.join("\n")}`);
  }
  return sections.join("\n");
}

function providerToolOutputAttachments(output: unknown): FileAttachment[] {
  if (!Array.isArray(output)) {
    return [];
  }
  const seen = new Set<string>();
  return output.flatMap((part) => {
    if (!isRecord(part) || part.type !== "attachment") {
      return [];
    }
    const attachment = attachmentFromRecord(part);
    if (attachment === null) {
      return [];
    }
    const identity = attachment.attachmentId ?? attachment.uri;
    if (seen.has(identity)) {
      return [];
    }
    seen.add(identity);
    return [attachment];
  });
}

/**
 * Provider-hosted tool calls render independently from Azents client-tool pairs.
 * The provider call event itself is the durable presentation unit.
 */
export function providerToolCallStatusFromPayload(
  payloadStatus: unknown,
  messageStatus: ChatMessage["status"],
): ProviderToolCall["status"] {
  switch (payloadStatus) {
    case "completed":
    case "failed":
    case "running":
      return payloadStatus;
    case "cancelled":
    case "interrupted":
      return "failed";
    default:
      return messageStatus === "partial" ? "running" : "unknown";
  }
}

export function providerToolCallFromPayload(
  payload: Record<string, unknown>,
  messageStatus: ChatMessage["status"],
): ProviderToolCall | null {
  const callId = stringField(payload, "call_id");
  const name = stringField(payload, "name");
  if (callId === null || name === null || !isRecord(payload.semantic)) {
    return null;
  }
  const semantic = payload.semantic;
  const input = semantic.input;
  if (
    (input !== null && typeof input !== "string") ||
    !("output" in semantic) ||
    !Array.isArray(semantic.references)
  ) {
    return null;
  }
  return {
    id: callId,
    callId,
    name,
    arguments: input ?? "",
    status: providerToolCallStatusFromPayload(payload.status, messageStatus),
    output: providerToolOutputText(semantic.output, semantic.references),
    attachments: providerToolOutputAttachments(semantic.output),
  };
}

export function applyProviderToolCallItem(
  prev: ChatMessage[],
  providerToolCall: ProviderToolCall,
  fallbackMsgId: string,
  createdAt: string,
  messageStatus: ChatMessage["status"] = "complete",
): ChatMessage[] {
  const semanticCallId = providerToolCall.callId ?? providerToolCall.id;
  const finalMsg: ChatMessage = {
    id: fallbackMsgId,
    role: "assistant",
    content: null,
    createdAt,
    status: messageStatus,
    providerToolCalls: [providerToolCall],
  };
  const idx = prev.findIndex(
    (message) =>
      message.id === fallbackMsgId ||
      message.providerToolCalls?.some(
        (toolCall) =>
          toolCall.callId === semanticCallId || toolCall.id === semanticCallId,
      ),
  );
  if (idx !== -1) {
    const next = [...prev];
    next[idx] = finalMsg;
    return next;
  }
  return [...prev, finalMsg];
}
