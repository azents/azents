"use client";

/**
 * Chat session view container.
 *
 * Owns the session-scoped external lookups and interaction state used by the
 * ChatSessionView UI surface.
 */

import { useMantineTheme } from "@mantine/core";
import { useFocusReturn, useMediaQuery } from "@mantine/hooks";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentContextPage } from "@/features/agents/AgentContextPage";
import { AgentSubagentsPage } from "@/features/agents/AgentSubagentsPage";
import { useRuntimeTerminalContainer } from "@/features/chat/containers/useRuntimeTerminalContainer";
import { useSubagentTreePanelContainer } from "@/features/chat/containers/useSubagentTreePanelContainer";
import { ScheduledTasksPage } from "@/features/scheduled-tasks/ScheduledTasksPage";
import { SessionChannelsPage } from "@/features/session-channels/SessionChannelsPage";
import { isTerminalProjectionConnectable } from "@/shared/runtime-terminal/protocol";
import { resolveComposerSubscriptionSelection } from "@/shared/subscription-usage/composerSubscriptionUsage";
import { trpc } from "@/trpc/client";
import { ChatSessionView } from "../components/ChatSessionView";
import { useSessionPanelState } from "../session-panel/useSessionPanelState";
import {
  resolveSubagentNavigation,
  type SubagentNavigationLinks,
} from "../subagentNavigation";
import { useWorkspacePanelContainer } from "../workspace/containers/useWorkspacePanelContainer";
import { useAgentSessionTitleUpdater } from "./useAgentSessionTitleUpdater";
import { useChatSessionContainer } from "./useChatSessionContainer";
import { useSubscriptionUsageContainer } from "./useSubscriptionUsageContainer";
import type { CurrentWorkspaceProfile } from "../senderPresentation";
import type { SessionPanelState } from "../session-panel/useSessionPanelState";
import type { ConnectionStatus } from "../types";
import type { WorkspacePanelContainerOutput } from "../workspace/containers/useWorkspacePanelContainer";
import type { RuntimeTerminalContainerOutput } from "@/shared/runtime-terminal/types";
import type { ComposerSubscriptionUsagePresentationProps } from "@/shared/subscription-usage/ComposerSubscriptionUsage";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";
import type { ReactNode } from "react";

export interface ChatSessionViewContainerProps {
  handle: string;
  /** URL-selected AgentSession ID */
  sessionId: string;
  /** This session's agent. */
  agent: AgentResponse;
  /** Loaded AgentSession metadata. */
  session: AgentSessionResponse;
  /** Pushes this session's connection status to the parent sidebar badge. */
  onConnectionStatusChange: (status: ConnectionStatus) => void;
}

export interface ChatSessionViewContainerOutput {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  headerSession: AgentSessionResponse;
  chatSession: ReturnType<typeof useChatSessionContainer>;
  currentWorkspaceProfile: CurrentWorkspaceProfile | null;
  subscriptionUsage: ComposerSubscriptionUsagePresentationProps | null;
  workspacePanel: WorkspacePanelContainerOutput;
  subagentNavigation: SubagentNavigationLinks | null;
  terminal: RuntimeTerminalContainerOutput;
  terminalMobile: boolean;
  panel: SessionPanelState;
  supportingContent: ReactNode;
  onSessionTitleChange: (session: AgentSessionResponse) => void;
  onUpdateTitle: (title: string | null) => Promise<AgentSessionResponse>;
}

export function useChatSessionViewContainer(
  props: ChatSessionViewContainerProps,
): ChatSessionViewContainerOutput {
  const { handle, sessionId, agent, session, onConnectionStatusChange } = props;
  const theme = useMantineTheme();
  const isWorkspacePanelDocked = useMediaQuery(
    `(min-width: ${theme.breakpoints.lg})`,
  );
  const panel = useSessionPanelState(!isWorkspacePanelDocked);
  useFocusReturn({ opened: !isWorkspacePanelDocked && panel.opened });
  const [headerSession, setHeaderSession] =
    useState<AgentSessionResponse>(session);
  const onUpdateTitle = useAgentSessionTitleUpdater(agent.id, sessionId);

  useEffect(() => {
    setHeaderSession(session);
  }, [session]);

  const chatSession = useChatSessionContainer({
    sessionId,
    agent,
    onConnectionStatusChange,
  });
  const currentWorkspaceProfileQuery = trpc.memberProfile.getMyProfile.useQuery(
    { handle },
    { retry: false },
  );
  const currentWorkspaceProfile =
    useMemo<CurrentWorkspaceProfile | null>(() => {
      const profile = currentWorkspaceProfileQuery.data;
      if (profile == null) {
        return null;
      }
      return { userId: profile.user_id, name: profile.name };
    }, [currentWorkspaceProfileQuery.data]);
  const subscriptionSelection = useMemo(
    () =>
      resolveComposerSubscriptionSelection(
        agent.selectable_model_options,
        chatSession.defaultInferenceProfile.model_target_label,
      ),
    [
      agent.selectable_model_options,
      chatSession.defaultInferenceProfile.model_target_label,
    ],
  );
  const subscriptionUsageContainer = useSubscriptionUsageContainer({
    enabled: subscriptionSelection !== null,
    handle,
    integrationId: subscriptionSelection?.integrationId ?? "",
    provider: subscriptionSelection?.provider ?? "",
  });
  const subscriptionUsage =
    subscriptionSelection === null
      ? null
      : {
          onRefresh: subscriptionUsageContainer.onRefresh,
          resetKey: subscriptionSelection.integrationId,
          state: subscriptionUsageContainer.state,
        };
  const workspacePanel = useWorkspacePanelContainer({
    handle,
    agentId: agent.id,
    sessionId,
    autoRefreshVisible:
      panel.opened &&
      (panel.activeView === "files" ||
        panel.activeView === "runtime" ||
        panel.activeView === "metrics"),
  });
  const terminal = useRuntimeTerminalContainer({
    handle,
    agentId: agent.id,
    sessionId,
    mobile: !isWorkspacePanelDocked,
  });
  const subagentTreePanel = useSubagentTreePanelContainer({
    agentId: agent.id,
    sessionId,
    pollingEnabled: false,
  });
  const subagentNavigation = useMemo((): SubagentNavigationLinks | null => {
    if (subagentTreePanel.state.type !== "LOADED") {
      return null;
    }
    return resolveSubagentNavigation(subagentTreePanel.state.tree);
  }, [subagentTreePanel.state]);

  useEffect(() => {
    if (
      panel.opened &&
      panel.activeView === "terminal" &&
      agent.effective_terminal_enabled &&
      isTerminalProjectionConnectable(terminal.projection?.state ?? null) &&
      terminal.presentation === "collapsed"
    ) {
      terminal.onExpand();
    }
  }, [
    panel.opened,
    panel.activeView,
    terminal,
    agent.effective_terminal_enabled,
  ]);

  let supportingContent: ReactNode = null;
  const supportingProps = { handle, agent, sessionId, session: headerSession };
  switch (panel.activeView) {
    case "context":
    case "system-prompt":
    case "raw-events":
      supportingContent = (
        <AgentContextPage {...supportingProps} view={panel.activeView} />
      );
      break;
    case "subagents":
      supportingContent = <AgentSubagentsPage {...supportingProps} />;
      break;
    case "channels":
      supportingContent = <SessionChannelsPage {...supportingProps} />;
      break;
    case "scheduled-tasks":
      supportingContent = (
        <ScheduledTasksPage
          {...supportingProps}
          initialTaskId={panel.initialTaskId}
          openInitialTaskForEdit={panel.openInitialTaskForEdit}
        />
      );
      break;
    default:
      break;
  }
  const onSessionTitleChange = useCallback(
    (nextSession: AgentSessionResponse): void => {
      setHeaderSession(nextSession);
    },
    [],
  );

  return {
    handle,
    agent,
    sessionId,
    headerSession,
    chatSession,
    currentWorkspaceProfile,
    subscriptionUsage,
    workspacePanel,
    subagentNavigation,
    terminal,
    terminalMobile: !isWorkspacePanelDocked,
    panel,
    supportingContent,
    onSessionTitleChange,
    onUpdateTitle,
  };
}

export function ChatSessionViewContainer(
  props: ChatSessionViewContainerProps,
): React.ReactElement {
  const output = useChatSessionViewContainer(props);
  return <ChatSessionView {...output} />;
}
