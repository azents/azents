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
  FocusTrap,
  Group,
  Menu,
  rem,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconArrowLeft,
  IconArrowUp,
  IconCalendarClock,
  IconChartBar,
  IconCode,
  IconDotsVertical,
  IconFileText,
  IconFolder,
  IconGripVertical,
  IconHome,
  IconPlugConnected,
  IconRobot,
  IconSettings,
  IconTerminal2,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentSessionHeader } from "@/shared/agent-session/AgentSessionHeader";
import { RuntimeTerminalPanel } from "@/shared/runtime-terminal/components/RuntimeTerminalPanel";
import { ComposerSubscriptionUsagePopoverWithBoundary } from "@/shared/subscription-usage/ComposerSubscriptionUsage";
import { SessionSidePanel } from "../session-panel/SessionSidePanel";
import { WorkspacePanelContainer } from "../workspace/containers/WorkspacePanelContainer";
import classes from "./ChatSessionView.module.css";
import { ChatView } from "./ChatView";
import type { ChatSessionViewContainerOutput } from "../containers/useChatSessionViewContainer";
import type { SessionPanelItem } from "../session-panel/SessionSidePanel";

function sessionHref(
  handle: string,
  agentId: string,
  sessionId: string,
): string {
  return `/w/${handle}/agents/${agentId}/sessions/${sessionId}`;
}

export function ChatSessionView({
  handle,
  agent,
  headerSession,
  chatSession,
  currentWorkspaceProfile,
  subscriptionUsage,
  workspacePanel,
  subagentNavigation,
  terminal,
  terminalMobile,
  panel,
  supportingContent,
  onSessionTitleChange,
  onUpdateTitle,
}: ChatSessionViewContainerOutput): React.ReactElement {
  const t = useTranslations("chat");
  const tAgentDetail = useTranslations("workspace.agents.detail");
  const panelItems: SessionPanelItem[] = [
    {
      id: "files",
      label: t("sessionPanel.files"),
      icon: <IconFolder size={rem(16)} />,
    },
    {
      id: "context",
      label: tAgentDetail("tabs.context"),
      icon: <IconChartBar size={rem(16)} />,
    },
    {
      id: "subagents",
      label: tAgentDetail("subagents.title"),
      icon: <IconRobot size={rem(16)} />,
    },
    {
      id: "channels",
      label: tAgentDetail("tabs.channels"),
      icon: <IconPlugConnected size={rem(16)} />,
    },
    {
      id: "scheduled-tasks",
      label: tAgentDetail("tabs.scheduledTasks"),
      icon: <IconCalendarClock size={rem(16)} />,
    },
    {
      id: "runtime",
      label: t("sessionPanel.runtime"),
      icon: <IconSettings size={rem(16)} />,
    },
    ...(workspacePanel.state.type === "SERVER" ||
    workspacePanel.state.type === "REMOVING"
      ? [
          {
            id: "metrics" as const,
            label: t("workspacePanel.metricsTab"),
            icon: <IconChartBar size={rem(16)} />,
          },
        ]
      : []),
    ...(agent.effective_terminal_enabled
      ? [
          {
            id: "terminal" as const,
            label: t("sessionPanel.terminal"),
            icon: <IconTerminal2 size={rem(16)} />,
          },
        ]
      : []),
    {
      id: "system-prompt",
      label: t("context.systemPrompt.title"),
      icon: <IconFileText size={rem(16)} />,
    },
    {
      id: "raw-events",
      label: t("context.rawEventsPage.title"),
      icon: <IconCode size={rem(16)} />,
    },
  ];
  const workspaceSelected =
    panel.activeView === "files" ||
    panel.activeView === "runtime" ||
    panel.activeView === "metrics";
  const activePanelLabel =
    panelItems.find((item) => item.id === panel.activeView)?.label ??
    t("sessionPanel.files");
  const panelContent = (
    <SessionSidePanel
      items={panelItems}
      activeId={panel.activeView}
      onSelect={panel.onSelect}
      onClose={panel.onClose}
      title={terminalMobile ? t("sessionPanel.mobileTitle") : activePanelLabel}
      closeLabel={t("sessionPanel.close")}
      previousTabsLabel={t("sessionPanel.previousTabs")}
      nextTabsLabel={t("sessionPanel.nextTabs")}
      mobile={terminalMobile}
    >
      <Box
        h="100%"
        mih={0}
        style={{ display: workspaceSelected ? "block" : "none" }}
      >
        <WorkspacePanelContainer
          {...workspacePanel}
          navigation="external"
          activeTab={
            panel.activeView === "runtime"
              ? "settings"
              : panel.activeView === "metrics"
                ? "metrics"
                : "workspace"
          }
        />
      </Box>
      <Box
        h="100%"
        mih={0}
        style={{
          display: panel.activeView === "terminal" ? "flex" : "none",
          flexDirection: "column",
        }}
      >
        <RuntimeTerminalPanel
          terminal={terminal}
          mobile={terminalMobile}
          embedded
          onStartRuntime={workspacePanel.onStartRuntime}
        />
      </Box>
      {supportingContent}
    </SessionSidePanel>
  );

  return (
    <Box className={classes.shell}>
      <AgentSessionHeader
        agent={agent}
        session={headerSession}
        onUpdateTitle={onUpdateTitle}
        onSessionTitleChange={onSessionTitleChange}
        onTogglePanel={panel.opened ? panel.onClose : panel.onOpen}
        panelOpened={panel.opened}
        chatControls={
          subscriptionUsage === null ? null : (
            <ComposerSubscriptionUsagePopoverWithBoundary
              compact
              {...subscriptionUsage}
            />
          )
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
      <Box
        ref={panel.containerRef}
        className={classes.desktopLayout}
        flex={1}
        mih={0}
        style={{
          gridTemplateColumns:
            !terminalMobile && panel.opened
              ? `minmax(0, ${panel.chatRatio}fr) ${rem(8)} minmax(0, ${1 - panel.chatRatio}fr)`
              : "minmax(0, 1fr)",
        }}
      >
        <Box
          className={classes.desktopChat}
          h="100%"
          mih={0}
          miw={0}
          inert={terminalMobile && panel.opened}
          style={{
            visibility: terminalMobile && panel.opened ? "hidden" : "visible",
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
        {!terminalMobile && panel.opened && (
          <Box
            role="separator"
            aria-label={t("sessionPanel.resize")}
            aria-orientation="vertical"
            aria-valuenow={Math.round(panel.chatRatio * 100)}
            aria-valuemin={35}
            aria-valuemax={75}
            tabIndex={0}
            onPointerDown={panel.onResizeStart}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault();
                panel.onResizeBy(event.key === "ArrowLeft" ? -0.05 : 0.05);
              }
            }}
            style={{
              cursor: "col-resize",
              display: "flex",
              alignItems: "center",
              borderLeft: `${rem(1)} solid var(--mantine-color-default-border)`,
            }}
          >
            <IconGripVertical size={rem(8)} />
          </Box>
        )}
        {terminalMobile && (
          <FocusTrap active={panel.opened}>
            <Box
              className={classes.mobilePanel}
              h="100%"
              mih={0}
              miw={0}
              hidden={!panel.opened}
              onKeyDown={(event) => {
                if (
                  event.key === "Escape" &&
                  !event.defaultPrevented &&
                  panel.activeView !== "terminal" &&
                  event.target instanceof Element &&
                  !event.target.closest('[role="dialog"]')
                ) {
                  event.stopPropagation();
                  panel.onClose();
                }
              }}
              style={{
                display: panel.opened ? "block" : "none",
              }}
            >
              {panelContent}
            </Box>
          </FocusTrap>
        )}
      </Box>
      {!terminalMobile && (
        <Box
          className={classes.desktopPanel}
          h="100%"
          mih={0}
          miw={0}
          hidden={!panel.opened}
          onKeyDown={(event) => {
            if (
              event.key === "Escape" &&
              !event.defaultPrevented &&
              panel.activeView !== "terminal" &&
              event.target instanceof Element &&
              !event.target.closest('[role="dialog"]')
            ) {
              event.stopPropagation();
              panel.onClose();
            }
          }}
          style={{
            display: panel.opened ? "block" : "none",
            left: `calc(${panel.chatRatio * 100}% + ${rem(8 * (1 - panel.chatRatio))})`,
          }}
        >
          {panelContent}
        </Box>
      )}
    </Box>
  );
}
