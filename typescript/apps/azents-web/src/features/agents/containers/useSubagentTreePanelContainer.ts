import { trpc } from "@/trpc/client";
import type { SubagentTreePanelState } from "../components/SubagentTreePanel";

interface SubagentTreePanelContainerProps {
  agentId: string;
  sessionId: string;
}

interface SubagentTreePanelContainerOutput {
  state: SubagentTreePanelState;
}

export function useSubagentTreePanelContainer({
  agentId,
  sessionId,
}: SubagentTreePanelContainerProps): SubagentTreePanelContainerOutput {
  const treeQuery = trpc.chat.getSubagentTree.useQuery({
    agentId,
    sessionId,
  });

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
