import { trpc } from "@/trpc/client";
import type { SubagentTreePanelState } from "../components/SubagentTreePanel";

interface SubagentTreePanelContainerProps {
  agentId: string;
  sessionId: string;
  pollingEnabled?: boolean;
}

interface SubagentTreePanelContainerOutput {
  state: SubagentTreePanelState;
}

const SUBAGENT_TREE_REFETCH_INTERVAL_MS = 5_000;

export function useSubagentTreePanelContainer({
  agentId,
  sessionId,
  pollingEnabled = true,
}: SubagentTreePanelContainerProps): SubagentTreePanelContainerOutput {
  const treeQuery = trpc.chat.getSubagentTree.useQuery(
    {
      agentId,
      sessionId,
    },
    {
      refetchInterval: pollingEnabled
        ? SUBAGENT_TREE_REFETCH_INTERVAL_MS
        : false,
      refetchOnWindowFocus: true,
    },
  );

  if (treeQuery.isPending) {
    return { state: { type: "LOADING" } };
  }

  if (treeQuery.isError) {
    return { state: { type: "ERROR", message: treeQuery.error.message } };
  }

  if (typeof treeQuery.data === "undefined") {
    return { state: { type: "LOADING" } };
  }

  return { state: { type: "LOADED", tree: treeQuery.data } };
}
