import type { PendingMailboxEntry } from "./hooks/pendingMailboxState";
import type { ChatMessage, FileAttachment, PendingInputBuffer } from "./types";

function pendingAttachments(uris: string[]): FileAttachment[] {
  return uris.map((uri) => ({
    uri,
    mediaType: "application/octet-stream",
  }));
}

export function pendingInputBufferMessage(
  buffer: PendingInputBuffer,
  senderUserId: string | null,
): ChatMessage {
  const attachments =
    buffer.attachmentFiles ?? pendingAttachments(buffer.attachments);
  return {
    id: buffer.id,
    role: "user",
    content: buffer.content,
    action: buffer.action,
    createdAt: buffer.createdAt,
    status: "complete",
    senderUserId,
    metadata: buffer.metadata,
    inferenceProfile: buffer.requestedInferenceProfile,
    ...(attachments.length > 0 ? { attachments } : {}),
  };
}

export function pendingMailboxMessage(
  entry: PendingMailboxEntry,
  senderUserId: string | null,
): ChatMessage {
  const { item } = entry;
  const presentation = item.presentation;

  switch (presentation.type) {
    case "user_message": {
      const attachments = pendingAttachments(presentation.attachments ?? []);
      return {
        id: item.id,
        role: "user",
        content: presentation.content,
        createdAt: item.created_at,
        status: "complete",
        senderUserId,
        inferenceProfile: presentation.requested_inference_profile,
        ...(attachments.length > 0 ? { attachments } : {}),
      };
    }
    case "action_message":
      return {
        id: item.id,
        role: "user",
        content: presentation.message,
        action: presentation.action,
        createdAt: item.created_at,
        status: "complete",
        senderUserId,
        inferenceProfile: presentation.requested_inference_profile,
      };
    case "agent_message":
      return {
        id: item.id,
        role: "user",
        content: presentation.content,
        createdAt: item.created_at,
        status: "complete",
        metadata: {
          source: "agent_mailbox",
          message_kind: presentation.message_kind,
          source_path: `/${presentation.message_kind}`,
        },
      };
    case "external_channel_message":
      return {
        id: item.id,
        role: "user",
        content: presentation.body,
        createdAt: item.created_at,
        status: "complete",
        metadata: {
          source: "external_channel",
          provider: presentation.provider,
          resource_label: presentation.resource_label,
          resource_type: presentation.resource_type,
          provider_message_key: presentation.external_message_id,
          author_type: presentation.author_type,
          prompt_role: presentation.prompt_role,
          provider_created_at: item.created_at,
          ...(presentation.sender_display_name
            ? { sender_display_name: presentation.sender_display_name }
            : {}),
          ...(presentation.original_url
            ? { original_url: presentation.original_url }
            : {}),
        },
      };
    case "goal_continuation":
      return {
        id: item.id,
        role: "goal_continuation",
        content: null,
        createdAt: item.created_at,
        status: "complete",
        inferenceProfile: presentation.requested_inference_profile,
      };
    case "external_channel_continuation":
      return {
        id: item.id,
        role: "external_channel_continuation",
        content: null,
        createdAt: item.created_at,
        status: "complete",
        inferenceProfile: presentation.requested_inference_profile,
      };
    case "scheduled_task_trigger":
    case "scheduled_task_continuation":
      return {
        id: item.id,
        role: "user",
        content: presentation.content,
        createdAt: item.created_at,
        status: "complete",
        metadata: {
          source: "scheduled_task",
          message_kind: presentation.type,
        },
      };
  }
}
