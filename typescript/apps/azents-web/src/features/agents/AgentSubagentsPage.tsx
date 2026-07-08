"use client";

/** Agent Subagents page. */

import { Box } from "@mantine/core";
import { AgentSessionHeader } from "./components/AgentSessionHeader";
import { SubagentTreePanel } from "./components/SubagentTreePanel";
import { useSubagentTreePanelContainer } from "./containers/useSubagentTreePanelContainer";
import type { AgentResponse } from "@azents/public-client";

interface AgentSubagentsPageProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
}

export function AgentSubagentsPage({
  handle,
  agent,
  sessionId,
}: AgentSubagentsPageProps): React.ReactElement {
  const subagentTreePanel = useSubagentTreePanelContainer({
    agentId: agent.id,
    sessionId,
  });

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSessionHeader handle={handle} agent={agent} sessionId={sessionId} />
      <Box style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        <SubagentTreePanel
          handle={handle}
          agentId={agent.id}
          activeSessionId={sessionId}
          state={subagentTreePanel.state}
        />
      </Box>
    </Box>
  );
}
