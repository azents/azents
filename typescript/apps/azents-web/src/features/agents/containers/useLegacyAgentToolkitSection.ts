"use client";
import { useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import { projectLegacyAgentToolkitState } from "../legacyAgentToolkitState";
import type {
  AgentToolkitSectionIdentity,
  LegacyAgentToolkitSectionProps,
} from "../types";
import type {
  AgentToolkitResponse,
  ToolkitConfigResponse,
} from "@azents/public-client";

export function useLegacyAgentToolkitSection({
  handle,
  agentId,
}: AgentToolkitSectionIdentity): LegacyAgentToolkitSectionProps {
  const utils = trpc.useUtils();
  const [selectedToolkitId, setSelectedToolkitId] = useState<string | null>(
    null,
  );
  const agentToolkitsQuery = trpc.toolkit.listAgentToolkits.useQuery({
    handle,
    agentId,
  });
  const availableToolkitsQuery = trpc.toolkit.listAvailableConfigs.useQuery({
    handle,
  });
  const agentToolkits: AgentToolkitResponse[] = useMemo(
    () => agentToolkitsQuery.data?.items ?? [],
    [agentToolkitsQuery.data],
  );
  const availableToolkits: ToolkitConfigResponse[] = useMemo(
    () => availableToolkitsQuery.data?.items ?? [],
    [availableToolkitsQuery.data],
  );
  const attachedToolkitIds = useMemo(
    () => new Set(agentToolkits.map((item) => item.toolkit_id)),
    [agentToolkits],
  );
  const selectOptions = useMemo(
    () =>
      availableToolkits
        .filter((toolkit) => !attachedToolkitIds.has(toolkit.id))
        .map((toolkit) => ({
          value: toolkit.id,
          label: `${toolkit.name} (${toolkit.toolkit_type})`,
        })),
    [attachedToolkitIds, availableToolkits],
  );
  const attachMutation = trpc.toolkit.attachToAgent.useMutation({
    onSuccess: () => {
      void utils.toolkit.listAgentToolkits.invalidate({ handle, agentId });
      setSelectedToolkitId(null);
    },
  });
  const detachMutation = trpc.toolkit.detachFromAgent.useMutation({
    onSuccess: () => {
      void utils.toolkit.listAgentToolkits.invalidate({ handle, agentId });
    },
  });
  const state = projectLegacyAgentToolkitState(
    { agentToolkits, availableToolkits, selectOptions },
    agentToolkitsQuery.isLoading || availableToolkitsQuery.isLoading,
    agentToolkitsQuery.isError || availableToolkitsQuery.isError,
  );
  return {
    state,
    selectedToolkitId,
    onSelectionChange: setSelectedToolkitId,
    onAttach: (toolkitId) =>
      attachMutation.mutate({ handle, agentId, toolkitId }),
    onDetach: (agentToolkitId) =>
      detachMutation.mutate({ handle, agentId, agentToolkitId }),
  };
}
