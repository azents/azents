"use client";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type { AgentResponse } from "@azents/public-client";
interface AgentSidebarSectionProps {
  handle: string;
  onNavigate?: () => void;
}
const MAX_SIDEBAR_ROWS = 8;
function resolveActive(
  pathname: string,
  basePath: string,
): {
  agentId: string | null;
} {
  if (!pathname.startsWith(basePath)) {
    return { agentId: null };
  }
  const rest = pathname.slice(basePath.length + 1); // after basePath + "/"
  const parts = rest.split("/");
  // rest is like "agents/{agentId}/settings" or "agents/{agentId}/sessions/{sessionId}"
  if (parts[0] === "agents" && parts[1] && parts[1] !== "new") {
    const agentId = parts[1];
    return { agentId };
  }
  return { agentId: null };
}
export interface AgentSidebarSectionViewProps {
  onNavigate: AgentSidebarSectionProps["onNavigate"];
  t: ReturnType<typeof useTranslations<"workspace.sidebar">>;
  workspaceBase: string;
  agentsBase: string;
  agentsQuery: ReturnType<typeof trpc.agent.list.useQuery>;
  activeAgentId: string | null;
  query: string;
  setQuery: React.Dispatch<React.SetStateAction<string>>;
  sidebarAgents: { visible: AgentResponse[]; totalCount: number };
}
export function useAgentSidebarSectionController({
  handle,
  onNavigate,
}: AgentSidebarSectionProps): AgentSidebarSectionViewProps {
  const t = useTranslations("workspace.sidebar");
  const pathname = usePathname();
  const workspaceBase = `/w/${handle}`;
  const agentsBase = `${workspaceBase}/agents`;

  const agentsQuery = trpc.agent.list.useQuery({ handle });

  const { agentId: activeAgentId } = useMemo(
    () => resolveActive(pathname, workspaceBase),
    [pathname, workspaceBase],
  );

  const [query, setQuery] = useState("");

  const sidebarAgents = useMemo(() => {
    const items = agentsQuery.data?.items ?? [];
    const q = query.toLowerCase();
    const filtered = items
      .filter((a) => a.enabled)
      .filter(
        (a) =>
          !q ||
          a.name.toLowerCase().includes(q) ||
          (a.description ?? "").toLowerCase().includes(q),
      );

    // Separately pick active agent to always include it.
    const alwaysInclude = activeAgentId
      ? filtered.filter((agent) => agent.id === activeAgentId)
      : [];
    const recent = filtered
      .filter((agent) => agent.id !== activeAgentId)
      .sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );

    const slots = Math.max(0, MAX_SIDEBAR_ROWS - alwaysInclude.length);
    const visible = [...alwaysInclude, ...recent.slice(0, slots)];
    return { visible, totalCount: filtered.length };
  }, [agentsQuery.data, query, activeAgentId]);
  return {
    onNavigate,
    t,
    workspaceBase,
    agentsBase,
    agentsQuery,
    activeAgentId,
    query,
    setQuery,
    sidebarAgents,
  };
}
