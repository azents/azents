export type ExternalChannelSettingsMutation =
  | "setup"
  | "validate"
  | "switchTransport"
  | "reconnect"
  | "disconnect"
  | "revokeGrant"
  | "removeBlock";

export type ExternalChannelSettingsQuery =
  | "connections"
  | "agentAccess"
  | "sessionChannels";

export function externalChannelSettingsInvalidationPlan(
  mutation: ExternalChannelSettingsMutation,
): readonly ExternalChannelSettingsQuery[] {
  switch (mutation) {
    case "setup":
    case "validate":
    case "switchTransport":
    case "reconnect":
      return ["connections"];
    case "disconnect":
      return ["connections", "sessionChannels"];
    case "revokeGrant":
      return ["agentAccess", "sessionChannels"];
    case "removeBlock":
      return ["agentAccess"];
  }
}
