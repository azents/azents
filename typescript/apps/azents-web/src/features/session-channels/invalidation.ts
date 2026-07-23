export type SessionChannelsQuery = "sessionChannels" | "connections";

export function sessionChannelDisconnectInvalidationPlan(): readonly SessionChannelsQuery[] {
  return ["sessionChannels", "connections"];
}
