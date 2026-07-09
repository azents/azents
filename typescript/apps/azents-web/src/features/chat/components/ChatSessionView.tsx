"use client";

/**
 * Single-session rendering component.
 *
 * useChatSessionContainer  call sessionper status owns and ChatView  to passes it..
 * parent(ChatPageContent) in `key` prop  per session with by setting  component
 * remount when WebSocket/buffer/timer fully isolateis. — previous session of stale
 * status text session with leakdoes not..
 */

import {
  ActionIcon,
  Box,
  Drawer,
  Group,
  Menu,
  rem,
  Text,
  Tooltip,
  useMantineTheme,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  IconArrowLeft,
  IconArrowUp,
  IconDotsVertical,
  IconGitBranch,
  IconHome,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AgentSessionHeader } from "@/features/agents/components/AgentSessionHeader";
import { SubagentTreePanel } from "@/features/agents/components/SubagentTreePanel";
import { useSubagentTreePanelContainer } from "@/features/agents/containers/useSubagentTreePanelContainer";
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
  SubagentTreeNodeResponse,
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

interface SubagentNavigationLinks {
  currentName: string;
  currentPath: string;
  parent: SubagentTreeNodeResponse;
  root: SubagentTreeNodeResponse;
}

function flattenSubagentNodes(
  nodes: SubagentTreeNodeResponse[],
): SubagentTreeNodeResponse[] {
  return nodes.flatMap((node) => [
    node,
    ...flattenSubagentNodes(node.children ?? []),
  ]);
}

function findSubagentNode(
  nodes: SubagentTreeNodeResponse[],
  sessionAgentId?: string | null,
): SubagentTreeNodeResponse | null {
  if (!sessionAgentId) {
    return null;
  }
  return nodes.find((node) => node.session_agent_id === sessionAgentId) ?? null;
}

function sessionHref(
  handle: string,
  agentId: string,
  sessionId: string,
): string {
  return `/w/${handle}/agents/${agentId}/sessions/${sessionId}`;
}

export function ChatSessionView({
  handle,
  sessionId,
  agent,
  session,
  onConnectionStatusChange,
}: ChatSessionViewProps): React.ReactElement {
  const t = useTranslations("chat");
  const tAgentDetail = useTranslations("workspace.agents.detail");
  const theme = useMantineTheme();
  const isWorkspacePanelDocked = useMediaQuery(
    `(min-width: ${theme.breakpoints.lg})`,
  );
  const [runtimeDrawerOpened, setRuntimeDrawerOpened] = useState(false);
  const [subagentDrawerOpened, setSubagentDrawerOpened] = useState(false);
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
  const subagentTreePanel = useSubagentTreePanelContainer({
    agentId: agent.id,
    sessionId,
  });
  const subagentNavigation = useMemo((): SubagentNavigationLinks | null => {
    if (subagentTreePanel.state.type !== "LOADED") {
      return null;
    }
    const tree = subagentTreePanel.state.tree;
    const nodes = flattenSubagentNodes(tree.nodes);
    const current = findSubagentNode(nodes, tree.current_session_agent_id);
    const root = findSubagentNode(nodes, tree.root_session_agent_id);
    const parent = findSubagentNode(nodes, current?.parent_session_agent_id);
    if (
      current === null ||
      root === null ||
      parent === null ||
      current.session_agent_id === root.session_agent_id
    ) {
      return null;
    }
    return {
      currentName: current.name,
      currentPath: current.path,
      parent,
      root,
    };
  }, [subagentTreePanel.state]);
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
          <Group gap="xs" wrap="nowrap">
            <TokenUsageIndicator
              usage={output.tokenUsage}
              effectiveContextWindowTokens={effectiveContextWindowTokens}
              autoCompactionThresholdTokens={
                agent.effective_auto_compaction_threshold_tokens
              }
              modelName={modelName}
            />
            <ActionIcon
              variant="subtle"
              radius="xl"
              onClick={() => setSubagentDrawerOpened(true)}
              aria-label={tAgentDetail("subagents.open")}
            >
              <IconGitBranch size={rem(18)} />
            </ActionIcon>
          </Group>
        }
      />
      {subagentNavigation !== null && (
        <Box
          px="md"
          py="xs"
          style={{
            borderBottom: `${rem(1)} solid var(--mantine-color-default-border)`,
            backgroundColor: "var(--mantine-color-body)",
          }}
        >
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <Tooltip
              label={tAgentDetail("subagents.backToParentTooltip", {
                name: subagentNavigation.parent.name,
                path: subagentNavigation.parent.path,
              })}
              withArrow
            >
              <ActionIcon
                component={Link}
                href={sessionHref(
                  handle,
                  agent.id,
                  subagentNavigation.parent.agent_session_id,
                )}
                size="sm"
                variant="subtle"
                aria-label={tAgentDetail("subagents.backToParent", {
                  name: subagentNavigation.parent.name,
                })}
              >
                <IconArrowLeft size={rem(18)} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label={subagentNavigation.currentPath} withArrow>
              <Text
                size="sm"
                fw={600}
                truncate
                style={{ minWidth: 0, flex: 1 }}
              >
                {subagentNavigation.currentName}
              </Text>
            </Tooltip>
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  aria-label={tAgentDetail("subagents.navigationMenu")}
                >
                  <IconDotsVertical size={rem(18)} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item
                  component={Link}
                  href={sessionHref(
                    handle,
                    agent.id,
                    subagentNavigation.parent.agent_session_id,
                  )}
                  leftSection={<IconArrowUp size={rem(14)} />}
                >
                  {tAgentDetail("subagents.parentLink", {
                    name: subagentNavigation.parent.name,
                  })}
                </Menu.Item>
                <Menu.Item
                  component={Link}
                  href={sessionHref(
                    handle,
                    agent.id,
                    subagentNavigation.root.agent_session_id,
                  )}
                  leftSection={<IconHome size={rem(14)} />}
                >
                  {tAgentDetail("subagents.rootLink", {
                    name: subagentNavigation.root.name,
                  })}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Box>
      )}
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
          readOnlyNotice={
            subagentNavigation === null
              ? null
              : tAgentDetail("subagents.inputDisabledPlaceholder")
          }
        />
      </Box>
      <Drawer
        opened={subagentDrawerOpened}
        onClose={() => setSubagentDrawerOpened(false)}
        title={tAgentDetail("subagents.title")}
        position="right"
        size="md"
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
        <SubagentTreePanel
          handle={handle}
          agentId={agent.id}
          activeSessionId={sessionId}
          state={subagentTreePanel.state}
          onNavigate={() => setSubagentDrawerOpened(false)}
        />
      </Drawer>
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
