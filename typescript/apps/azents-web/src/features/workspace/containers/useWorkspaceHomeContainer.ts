"use client";

/**
 * Workspace Home ("Our team agents") container.
 *
 * Builds primary/subagent lists and stats from `agent.list` response.
 * Persist tab state with URL `?view=`.
 */

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { formatModelSelectionSummary } from "@/features/agents/model-selection";
import { trpc } from "@/trpc/client";
import type {
  AgentTeamFilter,
  EnrichedAgent,
  WorkspaceHomeState,
  WorkspaceHomeStats,
} from "../types";
import type { AgentResponse } from "@azents/public-client";

const VIEW_PARAM = "view";
const DEFAULT_VIEW: AgentTeamFilter = "agents";
const VIEW_VALUES: ReadonlySet<AgentTeamFilter> = new Set([
  "agents",
  "subagents",
  "all",
]);
function isAgentTeamFilter(value: unknown): value is AgentTeamFilter {
  return typeof value === "string" && VIEW_VALUES.has(value as AgentTeamFilter);
}

function enrich(agent: AgentResponse): EnrichedAgent {
  return {
    ...agent,
    lastActiveAt: agent.updated_at,
    modelSummary: formatModelSelectionSummary(agent.model_selection),
  };
}

export interface WorkspaceHomeContainerProps {
  handle: string;
}

export interface WorkspaceHomeContainerOutput {
  handle: string;
  state: WorkspaceHomeState;
  /** Current tab */
  view: AgentTeamFilter;
  onViewChange: (value: AgentTeamFilter) => void;
  /** Search query */
  query: string;
  onQueryChange: (value: string) => void;
  /** Whether to include inactive */
  showDisabled: boolean;
  onShowDisabledChange: (value: boolean) => void;
  /** "N people" in subtitle — 0 while loading */
  membersCount: number;
}

export function useWorkspaceHomeContainer(
  props: WorkspaceHomeContainerProps,
): WorkspaceHomeContainerOutput {
  const { handle } = props;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const agentListQuery = trpc.agent.list.useQuery({ handle });
  const membersQuery = trpc.workspaceMember.list.useQuery({ handle });

  const state: WorkspaceHomeState = useMemo(() => {
    if (agentListQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (agentListQuery.isError) {
      return {
        type: "ERROR",
        message: agentListQuery.error.message,
      };
    }
    const allAgents = agentListQuery.data?.items ?? [];
    const enriched = allAgents.map((agent) => enrich(agent));
    const primaryAgents = enriched.filter((a) => a.role !== "subagent");
    const subagents = enriched.filter((a) => a.role === "subagent");

    const stats: WorkspaceHomeStats = {
      totalAgents: primaryAgents.length,
      enabledAgents: primaryAgents.filter((a) => a.enabled).length,
      subagentsCount: subagents.length,
    };

    return {
      type: "READY",
      primaryAgents,
      subagents,
      stats,
    };
  }, [
    agentListQuery.isLoading,
    agentListQuery.isError,
    agentListQuery.error,
    agentListQuery.data,
  ]);

  const viewRaw = searchParams.get(VIEW_PARAM);
  const view: AgentTeamFilter = isAgentTeamFilter(viewRaw)
    ? viewRaw
    : DEFAULT_VIEW;

  const onViewChange = useCallback(
    (value: AgentTeamFilter): void => {
      const next = new URLSearchParams(searchParams.toString());
      if (value === DEFAULT_VIEW) {
        next.delete(VIEW_PARAM);
      } else {
        next.set(VIEW_PARAM, value);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const [query, setQuery] = useState("");
  const [showDisabled, setShowDisabled] = useState(false);

  const membersCount = membersQuery.data?.items.length ?? 0;

  return {
    handle,
    state,
    view,
    onViewChange,
    query,
    onQueryChange: setQuery,
    showDisabled,
    onShowDisabledChange: setShowDisabled,
    membersCount,
  };
}
