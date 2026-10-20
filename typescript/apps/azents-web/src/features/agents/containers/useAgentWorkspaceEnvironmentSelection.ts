"use client";

import { useState } from "react";
import { useAgentLifecycle } from "@/shared/agent-session/useAgentLifecycle";
import { trpc } from "@/trpc/client";
import type { AgentWorkspaceEnvironmentSelectionProps } from "../components/AgentWorkspaceEnvironmentSelection";

export function useAgentWorkspaceEnvironmentSelection({
  handle,
  agentId,
}: {
  handle: string;
  agentId: string;
}): AgentWorkspaceEnvironmentSelectionProps {
  const { readOnly } = useAgentLifecycle({ handle, agentId });
  const utils = trpc.useUtils();
  const input = { handle, agentId };
  const query = trpc.workspace.getAgentEnvironmentSelection.useQuery(input);
  const [draft, setDraft] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const mutation = trpc.workspace.replaceAgentEnvironmentSelection.useMutation({
    onSuccess: async (settings) => {
      utils.workspace.getAgentEnvironmentSelection.setData(input, settings);
      setDraft(null);
      setSaved(true);
      await utils.workspace.getAgentEnvironmentSelection.invalidate(input);
    },
  });
  const selected = draft ?? query.data?.selected_ids ?? [];
  const stored = query.data?.selected_ids ?? [];
  const dirty =
    selected.length !== stored.length ||
    selected.some((id) => !stored.includes(id));
  return {
    handle,
    state: query.isError
      ? { type: "ERROR", message: query.error.message }
      : !query.data
        ? { type: "LOADING" }
        : {
            type: "READY",
            settings: {
              ...query.data,
              can_manage: query.data.can_manage && !readOnly,
            },
            selectedIds: selected,
            dirty,
            saving: mutation.isPending,
            saved,
            error: mutation.isError ? mutation.error.message : null,
          },
    onToggle: (id, checked) => {
      setDraft(
        checked ? [...selected, id] : selected.filter((value) => value !== id),
      );
      setSaved(false);
      mutation.reset();
    },
    onSave: () => {
      if (!readOnly && query.data?.can_manage && !mutation.isPending && dirty) {
        mutation.mutate({ ...input, selectedIds: selected });
      }
    },
    onDiscard: () => {
      setDraft(null);
      setSaved(false);
      mutation.reset();
    },
    onRetry: () => {
      void utils.workspace.getAgentEnvironmentSelection.invalidate(input);
    },
  };
}
