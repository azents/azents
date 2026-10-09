import type {
  LegacyAgentToolkitSnapshot,
  LegacyAgentToolkitState,
} from "./types";

/** Query lifecycle never removes retained attachment rows or their detach controls. */
export function projectLegacyAgentToolkitState(
  snapshot: LegacyAgentToolkitSnapshot,
  loading: boolean,
  failed: boolean,
): LegacyAgentToolkitState {
  if (loading && failed) {
    return { type: "LOADING_ERROR", ...snapshot };
  }
  if (loading) {
    return { type: "LOADING", ...snapshot };
  }
  if (failed) {
    return { type: "ERROR", ...snapshot };
  }
  return { type: "READY", ...snapshot };
}
