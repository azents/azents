import type {
  PersonalToolkitAccessMode,
  PersonalToolkitAccessRequest,
  PersonalToolkitBatchEntry,
  PersonalToolkitResponse,
} from "@azents/public-client";

export interface ConnectionAccessDraft {
  baseline: PersonalToolkitResponse;
  mode: PersonalToolkitAccessMode;
  changes: Readonly<Record<string, boolean>>;
}

export function connectionAllows(
  draft: ConnectionAccessDraft,
  agentId: string,
): boolean {
  if (draft.mode === "all") {
    return true;
  }
  return (
    draft.changes[agentId] ??
    (draft.baseline.access_mode === "all" ||
      draft.baseline.selected_agent_ids.includes(agentId))
  );
}

export function changeConnectionAgent(
  draft: ConnectionAccessDraft,
  agentId: string,
  allowed: boolean,
): ConnectionAccessDraft {
  return {
    ...draft,
    mode: "selected",
    changes: { ...draft.changes, [agentId]: allowed },
  };
}

/** Only explicit deltas cross the boundary; a filtered list is never a write set. */
export function connectionAccessRequest(
  draft: ConnectionAccessDraft,
): PersonalToolkitAccessRequest {
  return {
    expected_mode: draft.baseline.access_mode,
    mode: draft.mode === draft.baseline.access_mode ? null : draft.mode,
    allow_agent_ids:
      draft.mode === "all"
        ? []
        : Object.keys(draft.changes).filter(
            (id) =>
              draft.changes[id] &&
              !draft.baseline.selected_agent_ids.includes(id),
          ),
    restrict_agent_ids:
      draft.mode === "all"
        ? []
        : Object.keys(draft.changes).filter(
            (id) =>
              !draft.changes[id] &&
              (draft.baseline.access_mode === "all" ||
                draft.baseline.selected_agent_ids.includes(id)),
          ),
  };
}

export function toolkitAllowsAgent(
  toolkit: PersonalToolkitResponse,
  agentId: string,
): boolean {
  return (
    toolkit.access_mode === "all" ||
    toolkit.selected_agent_ids.includes(agentId)
  );
}

export function agentAccessRequests(
  baseline: readonly PersonalToolkitResponse[],
  agentId: string,
  changes: Readonly<Record<string, boolean>>,
): PersonalToolkitBatchEntry[] {
  return baseline.flatMap((toolkit) => {
    const allowed = changes[toolkit.id];
    if (allowed == null || allowed === toolkitAllowsAgent(toolkit, agentId)) {
      return [];
    }
    return [
      {
        toolkit_id: toolkit.id,
        expected_mode: toolkit.access_mode,
        mode: null,
        allow_agent_ids: allowed ? [agentId] : [],
        restrict_agent_ids: allowed ? [] : [agentId],
      },
    ];
  });
}
