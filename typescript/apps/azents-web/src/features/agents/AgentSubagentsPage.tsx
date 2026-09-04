"use client";

/** Agent Subagents page. */

import { Box } from "@mantine/core";
import { AgentSessionHeader } from "@/shared/agent-session/AgentSessionHeader";
import { SubagentTreePanel } from "./components/SubagentTreePanel";
import { useAgentSessionTitleUpdater } from "./containers/useAgentSessionTitleUpdater";
import { useSubagentTreePanelContainer } from "./containers/useSubagentTreePanelContainer";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

interface AgentSubagentsPageProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  session: AgentSessionResponse;
}

export function AgentSubagentsPage({
  handle,
  agent,
  sessionId,
  session,
}: AgentSubagentsPageProps): React.ReactElement {
  const subagentTreePanel = useSubagentTreePanelContainer({
    agentId: agent.id,
    sessionId,
  });
  const onUpdateTitle = useAgentSessionTitleUpdater(agent.id, sessionId);

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSessionHeader
        handle={handle}
        agent={agent}
        sessionId={sessionId}
        session={session}
        onUpdateTitle={onUpdateTitle}
      />
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
