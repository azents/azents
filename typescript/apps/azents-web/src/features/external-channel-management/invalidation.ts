export type ExternalChannelSettingsMutation =
  | "setup"
  | "validate"
  | "update"
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
    case "update":
      return ["connections"];
    case "disconnect":
      return ["connections", "sessionChannels"];
    case "revokeGrant":
      return ["agentAccess", "sessionChannels"];
    case "removeBlock":
      return ["agentAccess"];
  }
}
