"use client";

/**
 * Single-session rendering component.
 *
 * useChatSessionContainer  call sessionper status owns and ChatView  to passes it..
 * parent(ChatPageContent) in `key` prop  per session with by setting  component
 * remount when WebSocket/buffer/timer fully isolateis. — previous session of stale
 * status text session with leakdoes not..
 */

import { Box, Drawer } from "@mantine/core";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { AgentHeader } from "@/features/agents/components/AgentHeader";
import { formatModelSelectionSummary } from "@/features/agents/model-selection";
import { useChatSessionContainer } from "../containers/useChatSessionContainer";
import { WorkspacePanel } from "../workspace/components/WorkspacePanel";
import { useWorkspacePanelContainer } from "../workspace/containers/useWorkspacePanelContainer";
import { ChatView } from "./ChatView";
import { TokenUsageIndicator } from "./TokenUsageIndicator";
import type { ConnectionStatus } from "../types";
import type { AgentResponse } from "@azents/public-client";

interface ChatSessionViewProps {
  handle: string;
  /** mount time of session ID (new chat null) */
  initialSessionId: string | null;
  /** this session agent */
  agent: AgentResponse;
  /** server new session createtext when parent notice */
  onSessionCreated: (sessionId: string) => void;
  /** connection status parent to push (for sidebar badge) */
  onConnectionStatusChange: (status: ConnectionStatus) => void;
}

export function ChatSessionView({
  handle,
  initialSessionId,
  agent,
  onSessionCreated,
  onConnectionStatusChange,
}: ChatSessionViewProps): React.ReactElement {
  const t = useTranslations("chat");
  const [runtimeDrawerOpened, setRuntimeDrawerOpened] = useState(false);
  const output = useChatSessionContainer({
    initialSessionId,
    agent,
    onSessionCreated,
    onConnectionStatusChange,
  });
  const workspacePanel = useWorkspacePanelContainer({
    handle,
    agentId: agent.id,
  });
  const effectiveContextWindowTokens =
    agent.effective_context_window_tokens ?? null;
  const modelName = formatModelSelectionSummary(agent.model_selection);

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentHeader
        handle={handle}
        agent={agent}
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
          handle={handle}
          onSendMessage={output.onSendMessage}
          onSendCommand={output.onSendCommand}
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
          isCompacting={output.isCompacting}
          wasCommandBlocked={output.wasCommandBlocked}
          isStopAvailable={output.isStopAvailable}
          isStopPending={output.isStopPending}
          onStopRequest={output.onStopRequest}
          slashCommands={output.slashCommands}
          authorizationRequests={output.authorizationRequests}
          onAuthorizationComplete={output.onAuthorizationComplete}
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
