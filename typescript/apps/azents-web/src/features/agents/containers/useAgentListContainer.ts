"use client";

/** Agent list container hook. */

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { AgentListState } from "../types";
import type { AgentResponse } from "@azents/public-client";

export interface AgentListContainerProps {
  handle: string;
}

export interface AgentListContainerOutput {
  handle: string;
  listState: AgentListState;
  canManage: boolean;
  onDelete: (agentId: string) => void;
  onToggleEnabled: (agent: AgentResponse, enabled: boolean) => void;
}

export function useAgentListContainer(
  props: AgentListContainerProps,
): AgentListContainerOutput {
  const { handle } = props;
  const utils = trpc.useUtils();
  const meQuery = trpc.workspaceMember.me.useQuery({ handle });
  const canManage = meQuery.data?.role === "owner";
  const listQuery = trpc.agent.list.useQuery({ handle });
  const agents = useMemo(() => listQuery.data?.items ?? [], [listQuery.data]);

  const listState: AgentListState = useMemo(() => {
    if (listQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (listQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", agents };
  }, [listQuery.isLoading, listQuery.isError, agents]);

  const removeMutation = trpc.agent.remove.useMutation({
    onSuccess: () => {
      void utils.agent.list.invalidate({ handle });
    },
  });

  const updateMutation = trpc.agent.update.useMutation({
    onSuccess: () => {
      void utils.agent.list.invalidate({ handle });
    },
  });

  const onDelete = useCallback(
    (agentId: string): void => {
      removeMutation.mutate({ handle, agentId });
    },
    [handle, removeMutation],
  );

  const onToggleEnabled = useCallback(
    (agent: AgentResponse, enabled: boolean): void => {
      updateMutation.mutate({ handle, agentId: agent.id, enabled });
    },
    [handle, updateMutation],
  );

  return { handle, listState, canManage, onDelete, onToggleEnabled };
}
