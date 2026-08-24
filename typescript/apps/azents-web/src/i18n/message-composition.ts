type MessageEntry = readonly [namespace: string, messages: unknown];

type ComposedMessages<Entries extends readonly MessageEntry[]> = {
  [Entry in Entries[number] as Entry[0]]: Entry[1];
};

export const MESSAGE_NAMESPACES = [
  "account",
  "agentWorkspacePicker",
  "appBar",
  "auth",
  "chat",
  "chatPreview",
  "common",
  "cta",
  "elevation",
  "externalChannelApproval",
  "features",
  "footer",
  "hero",
  "memberProfile",
  "metadata",
  "nav",
  "oauth",
  "oauthCallback",
  "security",
  "skills",
  "useCases",
  "workspace",
  "workspaces",
] as const;

export function composeMessages<const Entries extends readonly MessageEntry[]>(
  entries: Entries,
): ComposedMessages<Entries>;
export function composeMessages(
  entries: readonly MessageEntry[],
): Record<string, unknown> {
  const messages: Record<string, unknown> = {};

  for (const [namespace, namespaceMessages] of entries) {
    if (Object.hasOwn(messages, namespace)) {
      throw new Error(`Duplicate message namespace: ${namespace}`);
    }
    messages[namespace] = namespaceMessages;
  }

  return messages;
}
