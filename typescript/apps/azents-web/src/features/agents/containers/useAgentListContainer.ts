"use client";

/**
 * Agent list container hook.
 *
 * Handles Agent list fetch, delete, enabled toggle, and role filter.
 * role filter is managed by URL `?role=agent|subagent|all` (default "agent").
 */

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { AgentListState, AgentRoleFilter } from "../types";
import type { AgentResponse } from "@azents/public-client";

const ROLE_FILTER_PARAM = "role";
const DEFAULT_ROLE_FILTER: AgentRoleFilter = "agent";
const ROLE_FILTER_VALUES: ReadonlySet<AgentRoleFilter> = new Set([
  "agent",
  "subagent",
  "all",
]);

function isAgentRoleFilter(value: unknown): value is AgentRoleFilter {
  return (
    typeof value === "string" &&
    ROLE_FILTER_VALUES.has(value as AgentRoleFilter)
  );
}

function matchesFilter(agent: AgentResponse, filter: AgentRoleFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "subagent") {
    return agent.role === "subagent";
  }
  return agent.role !== "subagent";
}

export interface AgentListContainerProps {
  handle: string;
}

export interface AgentListContainerOutput {
  handle: string;
  listState: AgentListState;
  canManage: boolean;
  /** Current role filter — based on URL `?role=` */
  roleFilter: AgentRoleFilter;
  /** Counts by filter (for all/agent/subagent badges) */
  counts: { agent: number; subagent: number; all: number };
  onRoleFilterChange: (value: AgentRoleFilter) => void;
  onDelete: (agentId: string) => void;
  onToggleEnabled: (agent: AgentResponse, enabled: boolean) => void;
}

export function useAgentListContainer(
  props: AgentListContainerProps,
): AgentListContainerOutput {
  const { handle } = props;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const utils = trpc.useUtils();
  const meQuery = trpc.workspaceMember.me.useQuery({ handle });
  const canManage = meQuery.data?.role === "owner";
  const listQuery = trpc.agent.list.useQuery({ handle });
  const allAgents = useMemo(
    () => listQuery.data?.items ?? [],
    [listQuery.data],
  );

  const filterParamRaw = searchParams.get(ROLE_FILTER_PARAM);
  const roleFilter: AgentRoleFilter = isAgentRoleFilter(filterParamRaw)
    ? filterParamRaw
    : DEFAULT_ROLE_FILTER;

  const filteredAgents = useMemo(
    () => allAgents.filter((a) => matchesFilter(a, roleFilter)),
    [allAgents, roleFilter],
  );

  const counts = useMemo(() => {
    const subagent = allAgents.filter((a) => a.role === "subagent").length;
    const all = allAgents.length;
    return { agent: all - subagent, subagent, all };
  }, [allAgents]);

  const listState: AgentListState = useMemo(() => {
    if (listQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (listQuery.isError) {
      return { type: "ERROR" };
    }
    return {
      type: "READY",
      agents: filteredAgents,
    };
  }, [listQuery.isLoading, listQuery.isError, filteredAgents]);

  const onRoleFilterChange = useCallback(
    (value: AgentRoleFilter): void => {
      const next = new URLSearchParams(searchParams.toString());
      if (value === DEFAULT_ROLE_FILTER) {
        next.delete(ROLE_FILTER_PARAM);
      } else {
        next.set(ROLE_FILTER_PARAM, value);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, pathname, router],
  );

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

  return {
    handle,
    listState,
    canManage,
    roleFilter,
    counts,
    onRoleFilterChange,
    onDelete,
    onToggleEnabled,
  };
}
