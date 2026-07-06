"use client";

/**
 * Single-session rendering component.
 *
 * useChatSessionContainer  call sessionper status owns and ChatView  to passes it..
 * parent(ChatPageContent) in `key` prop  per session with by setting  component
 * remount when WebSocket/buffer/timer fully isolateis. — previous session of stale
 * status text session with leakdoes not..
 */

import { Box, Drawer, useMantineTheme } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { AgentSessionHeader } from "@/features/agents/components/AgentSessionHeader";
import { formatModelSelectionSummary } from "@/features/agents/model-selection";
import { useChatSessionContainer } from "../containers/useChatSessionContainer";
import { WorkspacePanel } from "../workspace/components/WorkspacePanel";
import { useWorkspacePanelContainer } from "../workspace/containers/useWorkspacePanelContainer";
import { ChatView } from "./ChatView";
import { TokenUsageIndicator } from "./TokenUsageIndicator";
import type { ConnectionStatus } from "../types";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

interface ChatSessionViewProps {
  handle: string;
  /** URL-selected AgentSession ID */
  sessionId: string;
  /** this session agent */
  agent: AgentResponse;
  /** Loaded AgentSession metadata */
  session: AgentSessionResponse;
  /** connection status parent to push (for sidebar badge) */
  onConnectionStatusChange: (status: ConnectionStatus) => void;
}

export function ChatSessionView({
  handle,
  sessionId,
  agent,
  session,
  onConnectionStatusChange,
}: ChatSessionViewProps): React.ReactElement {
  const t = useTranslations("chat");
  const theme = useMantineTheme();
  const isWorkspacePanelDocked = useMediaQuery(
    `(min-width: ${theme.breakpoints.lg})`,
  );
  const [runtimeDrawerOpened, setRuntimeDrawerOpened] = useState(false);
  const [headerSession, setHeaderSession] =
    useState<AgentSessionResponse>(session);
  useEffect(() => {
    setHeaderSession(session);
  }, [session]);
  const output = useChatSessionContainer({
    sessionId,
    agent,
    onConnectionStatusChange,
  });
  const workspacePanel = useWorkspacePanelContainer({
    handle,
    agentId: agent.id,
    sessionId,
    autoRefreshVisible: isWorkspacePanelDocked || runtimeDrawerOpened,
  });
  const effectiveContextWindowTokens =
    agent.effective_context_window_tokens ?? null;
  const modelName = formatModelSelectionSummary(agent.model_selection);

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSessionHeader
        handle={handle}
        agent={agent}
        sessionId={sessionId}
        session={headerSession}
        onSessionTitleChange={setHeaderSession}
        onOpenRuntime={() => setRuntimeDrawerOpened(true)}
        chatControls={
          <TokenUsageIndicator
            usage={output.tokenUsage}
            effectiveContextWindowTokens={effectiveContextWindowTokens}
            autoCompactionThresholdTokens={
              agent.effective_auto_compaction_threshold_tokens
            }
            modelName={modelName}
          />
        }
      />
      <Box flex={1} mih={0}>
        <ChatView
          chatViewState={output.chatViewState}
          chatTimelineState={output.chatTimelineState}
          messages={output.messages}
          pendingInputBuffers={output.pendingInputBuffers}
          activeAgent={agent}
          sessionId={output.sessionId}
          isResponsePending={output.isResponsePending}
          isWritePending={output.isWritePending}
          isModelResponsePending={output.isModelResponsePending}
          liveRun={output.liveRun}
          handle={handle}
          onSendInput={output.onSendInput}
          onDeletePendingInputBuffer={output.onDeletePendingInputBuffer}
          onClearGoal={output.onClearGoal}
          onUpdateGoal={output.onUpdateGoal}
          onPauseGoal={output.onPauseGoal}
          onResumeGoal={output.onResumeGoal}
          hasMore={output.hasMore}
          isLoadingMore={output.isLoadingMore}
          isLoadingNewer={output.isLoadingNewer}
          onLoadMore={output.onLoadMore}
          onLoadNewer={output.onLoadNewer}
          onResetToLatest={output.onResetToLatest}
          onSubmitMessageEdit={output.onSubmitMessageEdit}
          onRetryFailedRun={output.onRetryFailedRun}
          isCompacting={output.isCompacting}
          wasCommandBlocked={output.wasCommandBlocked}
          isStopAvailable={output.isStopAvailable}
          isStopPending={output.isStopPending}
          onStopRequest={output.onStopRequest}
          inputActions={output.inputActions}
          authorizationRequests={output.authorizationRequests}
          onAuthorizationComplete={output.onAuthorizationComplete}
          actionExecutions={output.actionExecutions}
          onRetryActionExecution={output.onRetryActionExecution}
          onDiscardActionExecution={output.onDiscardActionExecution}
          workspacePanel={workspacePanel}
          goal={output.goal}
          todo={output.todo}
        />
      </Box>
      <Drawer
        hiddenFrom="lg"
        opened={runtimeDrawerOpened}
        onClose={() => setRuntimeDrawerOpened(false)}
        title={t("workspacePanel.title")}
        position="right"
        size="lg"
        styles={{
          body: {
            flex: 1,
            minHeight: 0,
            overflow: "hidden",
            padding: 0,
          },
          content: {
            display: "flex",
            flexDirection: "column",
            height: "100dvh",
            overflow: "hidden",
          },
          header: { flexShrink: 0 },
        }}
      >
        <Box h="100%" mih={0}>
          <WorkspacePanel {...workspacePanel} />
        </Box>
      </Drawer>
    </Box>
  );
}
