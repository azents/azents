"use client";

/**
 * Single-session chat UI surface.
 *
 * Session-scoped state, external lookups, and callbacks are owned by
 * useChatSessionViewContainer.
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
} from "@mantine/core";
import {
  IconArrowLeft,
  IconArrowUp,
  IconDotsVertical,
  IconHome,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentSessionHeader } from "@/shared/agent-session/AgentSessionHeader";
import { RuntimeTerminalPanel } from "@/shared/runtime-terminal/components/RuntimeTerminalPanel";
import { ComposerSubscriptionUsagePopoverWithBoundary } from "@/shared/subscription-usage/ComposerSubscriptionUsage";
import { WorkspacePanelContainer } from "../workspace/containers/WorkspacePanelContainer";
import { ChatView } from "./ChatView";
import type { ChatSessionViewContainerOutput } from "../containers/useChatSessionViewContainer";

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
  headerSession,
  chatSession,
  currentWorkspaceProfile,
  subscriptionUsage,
  workspacePanel,
  subagentNavigation,
  terminal,
  terminalMobile,
  runtimeDrawerOpened,
  onSessionTitleChange,
  onUpdateTitle,
  onOpenRuntime,
  onCloseRuntime,
}: ChatSessionViewContainerOutput): React.ReactElement {
  const t = useTranslations("chat");
  const tAgentDetail = useTranslations("workspace.agents.detail");

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSessionHeader
        handle={handle}
        agent={agent}
        sessionId={sessionId}
        session={headerSession}
        onUpdateTitle={onUpdateTitle}
        onSessionTitleChange={onSessionTitleChange}
        onOpenRuntime={onOpenRuntime}
        chatControls={
          subscriptionUsage === null ? null : (
            <ComposerSubscriptionUsagePopoverWithBoundary
              compact
              {...subscriptionUsage}
            />
          )
        }
      />
      {subagentNavigation !== null && terminal.presentation !== "focused" && (
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
      <Box
        flex={1}
        mih={0}
        style={{
          display: terminal.presentation === "focused" ? "none" : "block",
        }}
      >
        <ChatView
          chatViewState={chatSession.chatViewState}
          chatTimelineState={chatSession.chatTimelineState}
          messages={chatSession.messages}
          timelineEvents={chatSession.timelineEvents}
          pendingInputBuffers={chatSession.pendingInputBuffers}
          pendingMailboxEntries={chatSession.pendingMailboxEntries}
          activeAgent={agent}
          appliedInferenceProfile={chatSession.appliedInferenceProfile}
          sessionId={chatSession.sessionId}
          isResponsePending={chatSession.isResponsePending}
          isModelResponsePending={chatSession.isModelResponsePending}
          isWritePending={chatSession.isWritePending}
          lastEventReceivedAt={chatSession.lastEventReceivedAt}
          liveRun={chatSession.liveRun}
          tokenUsage={chatSession.tokenUsage}
          onApplyInferenceProfile={chatSession.onApplyInferenceProfile}
          defaultInferenceProfile={chatSession.defaultInferenceProfile}
          onSendInput={chatSession.onSendInput}
          onDeletePendingInputBuffer={chatSession.onDeletePendingInputBuffer}
          onClearGoal={chatSession.onClearGoal}
          onUpdateGoal={chatSession.onUpdateGoal}
          onPauseGoal={chatSession.onPauseGoal}
          onResumeGoal={chatSession.onResumeGoal}
          hasMore={chatSession.hasMore}
          isLoadingMore={chatSession.isLoadingMore}
          isLoadingNewer={chatSession.isLoadingNewer}
          onLoadMore={chatSession.onLoadMore}
          onLoadNewer={chatSession.onLoadNewer}
          onResetToLatest={chatSession.onResetToLatest}
          onSubmitMessageEdit={chatSession.onSubmitMessageEdit}
          onRetryFailedRun={chatSession.onRetryFailedRun}
          wasCommandBlocked={chatSession.wasCommandBlocked}
          isStopAvailable={chatSession.isStopAvailable}
          isStopPending={chatSession.isStopPending}
          onStopRequest={chatSession.onStopRequest}
          inputActions={chatSession.inputActions}
          authorizationRequests={chatSession.authorizationRequests}
          onAuthorizationComplete={chatSession.onAuthorizationComplete}
          actionExecutions={chatSession.actionExecutions}
          workspacePanel={workspacePanel}
          goal={chatSession.goal}
          todo={chatSession.todo}
          currentWorkspaceProfile={currentWorkspaceProfile}
          readOnlyNotice={
            subagentNavigation === null
              ? null
              : tAgentDetail("subagents.inputDisabledPlaceholder")
          }
        />
      </Box>
      <RuntimeTerminalPanel
        terminal={terminal}
        mobile={terminalMobile}
        onStartRuntime={workspacePanel.onStartRuntime}
      />
      <Drawer
        hiddenFrom="lg"
        opened={runtimeDrawerOpened}
        onClose={onCloseRuntime}
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
          <WorkspacePanelContainer {...workspacePanel} />
        </Box>
      </Drawer>
    </Box>
  );
}
