"use client";

import { AgentContextPage } from "@/features/agents/AgentContextPage";
import { AgentSubagentsPage } from "@/features/agents/AgentSubagentsPage";
import { AgentChatTabPage } from "@/features/chat/AgentChatTabPage";
import { ScheduledTasksPage } from "@/features/scheduled-tasks/ScheduledTasksPage";
import { SessionBrowserPage } from "@/features/session-browser/SessionBrowserPage";
import { SessionChannelsPage } from "@/features/session-channels/SessionChannelsPage";
import type { AgentChatContainerProps } from "@/features/chat/containers/useAgentChatContainer";
import type { SupportingPanelProps } from "@/features/chat/session-panel/supportingPanel";
import type { ReactNode } from "react";

function supportingContent({
  handle,
  agent,
  sessionId,
  session,
  panel,
}: SupportingPanelProps): ReactNode {
  const supportingProps = { handle, agent, sessionId, session };
  switch (panel.activeView) {
    case "browser":
      return agent.browser_enabled && panel.opened ? (
        <SessionBrowserPage
          handle={handle}
          agentId={agent.id}
          sessionId={sessionId}
        />
      ) : null;
    case "context":
    case "system-prompt":
    case "raw-events":
      return <AgentContextPage {...supportingProps} view={panel.activeView} />;
    case "subagents":
      return <AgentSubagentsPage {...supportingProps} />;
    case "channels":
      return <SessionChannelsPage {...supportingProps} />;
    case "scheduled-tasks":
      return (
        <ScheduledTasksPage
          {...supportingProps}
          activationRevision={panel.activationRevision}
          initialTaskId={panel.initialTaskId}
          openInitialTaskForEdit={panel.openInitialTaskForEdit}
        />
      );
    default:
      return null;
  }
}

export function AgentSessionPage(
  props: Omit<AgentChatContainerProps, "renderSupportingContent">,
): React.ReactElement {
  return (
    <AgentChatTabPage {...props} renderSupportingContent={supportingContent} />
  );
}
