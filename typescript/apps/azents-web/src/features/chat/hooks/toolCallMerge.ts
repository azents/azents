import type {
  ActiveToolCall,
  ChatMessage,
  FileAttachment,
  ToolkitSourceSnapshot,
  ToolResultStatus,
} from "../types";

/** FCO when arrives matched complete FC  to injectto result */
export interface FunctionCallOutputUpdate {
  callId: string;
  content: string;
  attachments: FileAttachment[];
  metadata?: Record<string, unknown>;
  status: ToolResultStatus;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringField(
  record: Record<string, unknown>,
  key: string,
): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

export function toolkitSourceFromValue(
  value: unknown,
): ToolkitSourceSnapshot | ActiveToolCall["toolkitSource"] {
  if (value === null || typeof value === "undefined") {
    return null;
  }
  if (!isRecord(value)) {
    return { kind: "invalid" };
  }
  const toolkitConfigId = stringField(value, "toolkit_config_id");
  const toolkitType = stringField(value, "toolkit_type");
  const toolkitName = stringField(value, "toolkit_name");
  const toolkitSlug = stringField(value, "toolkit_slug");
  if (
    toolkitConfigId === null ||
    toolkitType === null ||
    toolkitName === null ||
    toolkitSlug === null
  ) {
    return { kind: "invalid" };
  }
  return {
    toolkit_config_id: toolkitConfigId,
    toolkit_type: toolkitType,
    toolkit_name: toolkitName,
    toolkit_slug: toolkitSlug,
  };
}

/**
 * complete function_call_item  text complete tool item  with reflects..
 *
 * partial/live item and complete/durable item  different different item so with call_id  with
 * existing partial tool card  texti updatedoes not.. partial remove
 * live_event_removed event is responsible..
 */
export function applyFunctionCallItem(
  prev: ChatMessage[],
  toolCall: ActiveToolCall,
  fallbackMsgId: string,
  createdAt: string,
  messageStatus: ChatMessage["status"] = "complete",
): ChatMessage[] {
  const finalMsg: ChatMessage = {
    id: fallbackMsgId,
    role: "assistant",
    content: null,
    createdAt,
    status: messageStatus,
    toolCalls: [toolCall],
  };
  const idx = prev.findIndex((m) => m.id === fallbackMsgId);
  if (idx !== -1) {
    const next = [...prev];
    next[idx] = finalMsg;
    return next;
  }
  return [...prev, finalMsg];
}

export function applyFunctionCallOutput(
  prev: ChatMessage[],
  update: FunctionCallOutputUpdate,
): ChatMessage[] {
  for (let i = prev.length - 1; i >= 0; i--) {
    const msg = prev[i];
    if (
      !msg ||
      msg.role !== "assistant" ||
      msg.status !== "complete" ||
      !msg.toolCalls
    ) {
      continue;
    }
    const tcIdx = msg.toolCalls.findIndex(
      (tc) => tc.id === update.callId || tc.callId === update.callId,
    );
    if (tcIdx === -1) {
      continue;
    }
    const tc = msg.toolCalls[tcIdx];
    if (!tc) {
      continue;
    }
    const next = [...prev];
    const updatedToolCalls = [...msg.toolCalls];
    updatedToolCalls[tcIdx] = {
      ...tc,
      status: update.status,
      result: update.content,
      ...(typeof update.metadata === "undefined"
        ? {}
        : { resultMetadata: update.metadata }),
      ...(update.attachments.length > 0
        ? { attachments: update.attachments }
        : {}),
    };
    next[i] = { ...msg, toolCalls: updatedToolCalls };
    return next;
  }
  return prev;
}
