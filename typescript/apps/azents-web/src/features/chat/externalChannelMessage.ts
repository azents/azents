import type { ChatMessage } from "./types";

export interface ExternalChannelMessagePresentation {
  provider: string;
  resourceLabel: string;
  resourceType: string;
  senderDisplayName: string;
  providerUserId: string | null;
  providerMessageKey: string | null;
  authorType: string;
  authorization: string;
  lifecycle: string;
  revisionKind: string;
  providerTimestamp: string;
  originalUrl: string | null;
  correctionOfRevisionId: string | null;
  body: string;
}

interface ReferenceMappings {
  users: Record<string, string>;
  channels: Record<string, string>;
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

function referenceMappings(
  metadata: Record<string, string>,
): ReferenceMappings {
  const fallback: ReferenceMappings = { users: {}, channels: {} };
  const raw = metadata.reference_mappings;
  if (!raw) {
    return fallback;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) {
      return fallback;
    }
    return {
      users: stringRecord(parsed.users),
      channels: stringRecord(parsed.channels),
    };
  } catch {
    return fallback;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stringRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) {
    return {};
  }
  const entries: Array<[string, string]> = [];
  for (const [identifier, displayName] of Object.entries(value)) {
    if (identifier && typeof displayName === "string" && displayName) {
      entries.push([identifier, displayName]);
    }
  }
  return Object.fromEntries(entries);
}

function visibleReferences(body: string, mappings: ReferenceMappings): string {
  return body
    .replace(
      /<@([A-Z0-9]+)(?:\|[^>]+)?>|@([UW][A-Z0-9]+)/g,
      (match: string, one?: string, two?: string) => {
        const identifier = one ?? two;
        if (!identifier) {
          return match;
        }
        const displayName = mappings.users[identifier];
        return displayName ? `@${displayName}` : match;
      },
    )
    .replace(
      /<#([CG][A-Z0-9]+)(?:\|[^>]+)?>|#([CG][A-Z0-9]+)/g,
      (match: string, one?: string, two?: string) => {
        const identifier = one ?? two;
        if (!identifier) {
          return match;
        }
        const displayName = mappings.channels[identifier];
        return displayName ? displayName : match;
      },
    );
}

function visibleResourceLabel(
  resourceLabel: string,
  mappings: ReferenceMappings,
): string {
  const channelId = resourceLabel.match(/^([CG][A-Z0-9]+)/)?.[1];
  return channelId
    ? (mappings.channels[channelId] ?? resourceLabel)
    : resourceLabel;
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
  const mappings = referenceMappings(metadata);
  const senderDisplayName = metadata.sender_display_name?.trim();
  return {
    provider: metadata.provider ?? "external",
    resourceLabel: visibleResourceLabel(
      metadata.resource_label ?? "Unknown resource",
      mappings,
    ),
    resourceType: metadata.resource_type ?? "resource",
    senderDisplayName:
      (senderDisplayName ||
        (metadata.provider_user_id
          ? (mappings.users[metadata.provider_user_id] ??
            metadata.provider_user_id)
          : null)) ??
      "Unknown sender",
    providerUserId: metadata.provider_user_id ?? null,
    providerMessageKey: metadata.provider_message_key ?? null,
    authorType: metadata.author_type ?? "unknown",
    authorization: metadata.authorization ?? "context_only",
    lifecycle,
    revisionKind: metadata.revision_kind ?? "original",
    providerTimestamp,
    originalUrl: validHttpUrl(metadata.original_url),
    correctionOfRevisionId: metadata.correction_of_revision_id ?? null,
    body: visibleReferences(visibleBody(message, lifecycle), mappings),
  };
}
