import type { ChatMessage } from "./types";

export interface ExternalChannelMessagePresentation {
  provider: string;
  resourceLabel: string;
  resourceType: string;
  senderDisplayName: string;
  authorType: string;
  authorization: string;
  lifecycle: string;
  revisionKind: string;
  providerTimestamp: string;
  originalUrl: string | null;
  correctionOfRevisionId: string | null;
  body: string;
}

function validHttpUrl(value?: string): string | null {
  if (!value) {
    return null;
  }
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

function visibleBody(message: ChatMessage, lifecycle: string): string {
  if (lifecycle === "deleted") {
    return "[Message deleted by provider.]";
  }
  const content = message.content?.trim();
  return content ? (message.content ?? "") : "[Message has no text content.]";
}

export function externalChannelMessagePresentation(
  message: ChatMessage,
): ExternalChannelMessagePresentation | null {
  const metadata = message.metadata;
  if (metadata?.source !== "external_channel") {
    return null;
  }
  const lifecycle = metadata.lifecycle ?? "active";
  const providerTimestamp =
    metadata.provider_updated_at ??
    metadata.provider_created_at ??
    message.createdAt;
  return {
    provider: metadata.provider ?? "external",
    resourceLabel: metadata.resource_label ?? "Unknown resource",
    resourceType: metadata.resource_type ?? "resource",
    senderDisplayName:
      metadata.sender_display_name ??
      metadata.provider_user_id ??
      "Unknown sender",
    authorType: metadata.author_type ?? "unknown",
    authorization: metadata.authorization ?? "context_only",
    lifecycle,
    revisionKind: metadata.revision_kind ?? "original",
    providerTimestamp,
    originalUrl: validHttpUrl(metadata.original_url),
    correctionOfRevisionId: metadata.correction_of_revision_id ?? null,
    body: visibleBody(message, lifecycle),
  };
}
