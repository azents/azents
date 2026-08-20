"use client";

import {
  Badge,
  Box,
  Center,
  Group,
  Loader,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconArrowDown,
  IconGripVertical,
  IconMessageOff,
} from "@tabler/icons-react";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { isCompactionInProgressMarker } from "../compactionPresentation";
import {
  type ChatViewContainerOutput,
  isBoundaryMessage,
  useChatViewContainer,
} from "../containers/useChatViewContainer";
import { WorkspacePanel } from "../workspace/components/WorkspacePanel";
import { ActionExecutionTimelineCard } from "./ActionExecutionTimelineCard";
import {
  chatScrollOverscrollBehavior,
  chatScrollViewportProps,
} from "./activityRowPresentation";
import { AgentRunIndicator } from "./AgentRunIndicator";
import { AuthorizationRequestBubble } from "./AuthorizationRequestBubble";
import { ChatInput } from "./ChatInput";
import { CompactionDivider } from "./CompactionDivider";
import { CompactionIndicator } from "./CompactionIndicator";
import { MessageBubble } from "./MessageBubble";
import { OptimisticInputBubble } from "./OptimisticInputBubble";
import { PendingInputBufferBubble } from "./PendingInputBufferBubble";
import { PendingMailboxBubble } from "./PendingMailboxBubble";
import { RunRetryCard } from "./RunRetryCard";
import { ToolActivityGroup } from "./ToolActivityGroup";
import type { ReactElement } from "react";

const NEW_MESSAGE_CHIP_OFFSET = "calc(100% + var(--mantine-spacing-xl))";

function ChatViewPresentation(output: ChatViewContainerOutput): ReactElement {
  const {
    t,
    chatViewState,
    chatTimelineState,
    pendingInputBuffers,
    pendingMailboxEntries,
    activeAgent,
    appliedInferenceProfile,
    defaultInferenceProfile,
    sessionId,
    isResponsePending,
    isModelResponsePending,
    isWritePending,
    lastEventReceivedAt,
    liveRun,
    onApplyInferenceProfile,
    tokenUsage,
    onDeletePendingInputBuffer,
    onClearGoal,
    onUpdateGoal,
    onPauseGoal,
    onResumeGoal,
    isLoadingMore,
    onRetryFailedRun,
    wasCommandBlocked,
    isStopAvailable,
    isStopPending,
    onStopRequest,
    inputActions,
    onAuthorizationComplete,
    workspacePanel,
    goal,
    todo,
    currentWorkspaceProfile,
    readOnlyNotice,
    splitContainerRef,
    scrollAreaRef,
    viewportRef,
    contentRef,
    chatRatio,
    handleWorkspaceResizeStart,
    hasTimelineItems,
    chatPresentationItems,
    activeActivitySource,
    activeActivity,
    actionExecutionPlacement,
    editingMessageIndex,
    latestCompactionIndex,
    completedCompactionIdSet,
    attachedAuthorizationRequest,
    unattachedAuthorizationRequests,
    activeRun,
    latestActivityId,
    latestVisibleId,
    liveRetryRun,
    liveOperationRun,
    hasDetachedNewer,
    showNewMessageChip,
    scrollToBottom,
    isMobile,
    editingMessage,
    isUploading,
    pendingFiles,
    uploadAll,
    handleSubmitInput,
    clearFiles,
    resetDoneFiles,
    addFiles,
    removeFile,
    handleAfterSend,
    handleInputFocus,
    handleCancelEdit,
    handleStartEdit,
  } = output;
  // empty status
  if (chatViewState.type === "EMPTY") {
    return (
      <Center h="100%">
        <Stack align="center" gap="md">
          <IconMessageOff size={48} color="var(--mantine-color-dimmed)" />
          <Text c="dimmed" ta="center" style={{ whiteSpace: "pre-line" }}>
            {t("selectAgent")}
          </Text>
        </Stack>
      </Center>
    );
  }

  // history loading
  if (chatViewState.type === "LOADING_HISTORY" && !hasTimelineItems) {
    return (
      <Center h="100%">
        <Stack align="center" gap="md">
          <Loader size="lg" />
          <Text c="dimmed">{t("loadingHistory")}</Text>
        </Stack>
      </Center>
    );
  }

  // chat view
  return (
    <Group
      ref={splitContainerRef}
      h="100%"
      mih={0}
      w="100%"
      gap={0}
      align="stretch"
      wrap="nowrap"
      style={{ overflow: "hidden" }}
    >
      <Stack
        h="100%"
        mih={0}
        miw={0}
        flex={1}
        gap={0}
        style={{
          backgroundColor: "var(--mantine-color-body)",
          position: "relative",
          overflow: "hidden",
          flexBasis: `${chatRatio * 100}%`,
        }}
      >
        {/* message area */}
        <ScrollArea
          flex={1}
          mih={0}
          ref={scrollAreaRef}
          viewportRef={viewportRef}
          overscrollBehavior={chatScrollOverscrollBehavior}
          viewportProps={chatScrollViewportProps}
          styles={{ root: { minWidth: 0 }, viewport: { minWidth: 0 } }}
        >
          <Box
            ref={contentRef}
            px="md"
            pb="md"
            maw={rem(920)}
            mx="auto"
            w="100%"
            pt="md"
          >
            {/* older messages loading indicator */}
            {isLoadingMore && (
              <Center py="sm">
                <Loader size="sm" />
              </Center>
            )}
            {!hasTimelineItems && !isResponsePending ? (
              <Center py="xl">
                <Text c="dimmed" size="sm">
                  {t("startConversation")}
                </Text>
              </Center>
            ) : (
              <Stack gap={0}>
                {chatPresentationItems.map((item) => {
                  if (item.type === "activity") {
                    const sourceActivity =
                      activeActivitySource?.id === item.id
                        ? activeActivity
                        : null;
                    const durableBefore =
                      actionExecutionPlacement.durableBeforeMessage.get(
                        item.activity.firstMessageId,
                      ) ?? [];
                    const dimmedByEdit =
                      editingMessageIndex !== null &&
                      item.activity.endMessageIndex >= editingMessageIndex;
                    return (
                      <Box key={item.id} data-chat-scroll-anchor>
                        {durableBefore.map((actionExecution) => (
                          <ActionExecutionTimelineCard
                            key={actionExecution.execution.id}
                            actionExecution={actionExecution}
                          />
                        ))}
                        <ToolActivityGroup
                          activity={sourceActivity ?? item.activity}
                          dimmed={dimmedByEdit}
                          active={sourceActivity !== null}
                          authorizationAction={
                            (sourceActivity !== null ||
                              (activeRun === null &&
                                item.id === latestActivityId)) &&
                            attachedAuthorizationRequest !== null ? (
                              <AuthorizationRequestBubble
                                variant="compact"
                                toolkitName={
                                  attachedAuthorizationRequest.toolkitName
                                }
                                authorizationUrl={
                                  attachedAuthorizationRequest.authorizationUrl
                                }
                                onAuthorized={() =>
                                  onAuthorizationComplete(
                                    attachedAuthorizationRequest.toolkitId,
                                  )
                                }
                              />
                            ) : null
                          }
                        />
                      </Box>
                    );
                  }

                  const msg = item.message;
                  const index = item.messageIndex;
                  const durableBefore =
                    actionExecutionPlacement.durableBeforeMessage.get(msg.id) ??
                    [];
                  if (msg.role === "compaction") {
                    return (
                      <Box key={item.id} data-chat-scroll-anchor>
                        {durableBefore.map((actionExecution) => (
                          <ActionExecutionTimelineCard
                            key={actionExecution.execution.id}
                            actionExecution={actionExecution}
                          />
                        ))}
                        <CompactionDivider content={msg.content} />
                      </Box>
                    );
                  }
                  if (msg.role === "compaction_started") {
                    if (
                      !isCompactionInProgressMarker(
                        msg,
                        completedCompactionIdSet,
                      )
                    ) {
                      return durableBefore.length > 0 ? (
                        <Box key={item.id} data-chat-scroll-anchor>
                          {durableBefore.map((actionExecution) => (
                            <ActionExecutionTimelineCard
                              key={actionExecution.execution.id}
                              actionExecution={actionExecution}
                            />
                          ))}
                        </Box>
                      ) : null;
                    }
                    return (
                      <Box key={item.id} data-chat-scroll-anchor>
                        {durableBefore.map((actionExecution) => (
                          <ActionExecutionTimelineCard
                            key={actionExecution.execution.id}
                            actionExecution={actionExecution}
                          />
                        ))}
                        <CompactionIndicator />
                      </Box>
                    );
                  }
                  if (isBoundaryMessage(msg)) {
                    return durableBefore.length > 0 ? (
                      <Box key={item.id} data-chat-scroll-anchor>
                        {durableBefore.map((actionExecution) => (
                          <ActionExecutionTimelineCard
                            key={actionExecution.execution.id}
                            actionExecution={actionExecution}
                          />
                        ))}
                      </Box>
                    ) : null;
                  }
                  const dimmedByEdit =
                    editingMessageIndex !== null &&
                    index >= editingMessageIndex;
                  const editableUserMessage =
                    readOnlyNotice === null &&
                    msg.role === "user" &&
                    msg.metadata?.source !== "external_channel" &&
                    Boolean(msg.content) &&
                    msg.status !== "partial" &&
                    index > latestCompactionIndex &&
                    !isResponsePending;
                  const failedRunRetryAction = msg.failedRunFailure
                    ? {
                        canRetry:
                          chatTimelineState.type === "LATEST_FOLLOWING" &&
                          msg.id === latestVisibleId &&
                          !isResponsePending &&
                          !isWritePending &&
                          !isStopAvailable &&
                          pendingInputBuffers.length === 0,
                        isPending: isWritePending,
                        onRetry: () => {
                          void onRetryFailedRun(msg.id);
                        },
                      }
                    : null;
                  return (
                    <Box key={item.id} data-chat-scroll-anchor>
                      {durableBefore.map((actionExecution) => (
                        <ActionExecutionTimelineCard
                          key={actionExecution.execution.id}
                          actionExecution={actionExecution}
                        />
                      ))}
                      <MessageBubble
                        message={msg}
                        currentWorkspaceProfile={currentWorkspaceProfile}
                        dimmed={dimmedByEdit}
                        editable={editableUserMessage}
                        onEdit={() => handleStartEdit(msg)}
                        failedRunRetryAction={failedRunRetryAction}
                      />
                    </Box>
                  );
                })}
                {activeActivity !== null &&
                  activeRun !== null &&
                  activeActivitySource === null && (
                    <ToolActivityGroup
                      activity={activeActivity}
                      active
                      authorizationAction={
                        attachedAuthorizationRequest !== null ? (
                          <AuthorizationRequestBubble
                            variant="compact"
                            toolkitName={
                              attachedAuthorizationRequest.toolkitName
                            }
                            authorizationUrl={
                              attachedAuthorizationRequest.authorizationUrl
                            }
                            onAuthorized={() =>
                              onAuthorizationComplete(
                                attachedAuthorizationRequest.toolkitId,
                              )
                            }
                          />
                        ) : null
                      }
                    />
                  )}
                {actionExecutionPlacement.durableTail.map((actionExecution) => (
                  <ActionExecutionTimelineCard
                    key={actionExecution.execution.id}
                    actionExecution={actionExecution}
                  />
                ))}
                {unattachedAuthorizationRequests.map((req) => (
                  <AuthorizationRequestBubble
                    key={req.toolkitId}
                    toolkitName={req.toolkitName}
                    authorizationUrl={req.authorizationUrl}
                    onAuthorized={() => onAuthorizationComplete(req.toolkitId)}
                  />
                ))}
                {liveRetryRun !== null && (
                  <RunRetryCard
                    variant="live"
                    retry={liveRetryRun.retry}
                    phase={liveRetryRun.phase}
                  />
                )}
                {liveOperationRun !== null && <CompactionIndicator />}
                {actionExecutionPlacement.liveTail.map((actionExecution) => (
                  <ActionExecutionTimelineCard
                    key={actionExecution.execution.id}
                    actionExecution={actionExecution}
                  />
                ))}
                {chatTimelineState.type === "LATEST_FOLLOWING" &&
                  isModelResponsePending && (
                    <AgentRunIndicator
                      lastEventReceivedAt={lastEventReceivedAt}
                    />
                  )}
                {chatTimelineState.type === "LATEST_FOLLOWING" &&
                  pendingMailboxEntries.map((entry) => (
                    <PendingMailboxBubble
                      key={`${entry.item.mailbox_item_id}:${entry.item.item_key}`}
                      entry={entry}
                      currentWorkspaceProfile={currentWorkspaceProfile}
                      onDelete={onDeletePendingInputBuffer}
                    />
                  ))}
                {chatTimelineState.type === "LATEST_FOLLOWING" &&
                  pendingInputBuffers.map((buffer) =>
                    buffer.id.startsWith("optimistic:") ? (
                      <OptimisticInputBubble
                        key={buffer.id}
                        buffer={buffer}
                        currentWorkspaceProfile={currentWorkspaceProfile}
                      />
                    ) : (
                      <PendingInputBufferBubble
                        key={buffer.id}
                        buffer={buffer}
                        currentWorkspaceProfile={currentWorkspaceProfile}
                        onDelete={onDeletePendingInputBuffer}
                      />
                    ),
                  )}
              </Stack>
            )}
          </Box>
        </ScrollArea>

        <Box
          bg="var(--mantine-color-body)"
          style={{ position: "relative", flexShrink: 0 }}
        >
          {/* new message notice chip */}
          {(showNewMessageChip || hasDetachedNewer) && (
            <Box
              style={{
                position: "absolute",
                bottom: NEW_MESSAGE_CHIP_OFFSET,
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: 2,
                pointerEvents: "auto",
              }}
            >
              <Badge
                component="button"
                type="button"
                size="lg"
                variant="filled"
                color="blue"
                rightSection={<IconArrowDown size={14} />}
                onClick={scrollToBottom}
                aria-label={t("newMessage")}
                style={{
                  cursor: "pointer",
                  boxShadow: "var(--mantine-shadow-md)",
                }}
              >
                {t("newMessage")}
              </Badge>
            </Box>
          )}
          {/* input area */}
          <Box px="md" py="sm">
            <Box maw={rem(920)} mx="auto">
              <ChatInput
                agentId={activeAgent?.id ?? null}
                sessionId={sessionId}
                isMobile={isMobile}
                selectableModelOptions={
                  activeAgent?.selectable_model_options ?? []
                }
                appliedInferenceProfile={appliedInferenceProfile}
                defaultInferenceProfile={defaultInferenceProfile}
                editingInferenceProfile={
                  editingMessage?.inferenceProfile ?? null
                }
                inferenceProfileSelectionEnabled={readOnlyNotice === null}
                contextUsageEnabled={sessionId !== null}
                contextUsage={tokenUsage}
                contextUsageActiveRun={liveRun}
                onApplyInferenceProfile={onApplyInferenceProfile}
                isUploading={isUploading || isWritePending}
                pendingFiles={readOnlyNotice === null ? pendingFiles : []}
                goal={
                  readOnlyNotice === null && editingMessage === null
                    ? goal
                    : null
                }
                todo={
                  readOnlyNotice === null && editingMessage === null
                    ? todo
                    : null
                }
                onClearGoal={onClearGoal}
                onUpdateGoal={onUpdateGoal}
                onPauseGoal={onPauseGoal}
                onResumeGoal={onResumeGoal}
                uploadAll={uploadAll}
                onSendInput={handleSubmitInput}
                clearFiles={clearFiles}
                resetDoneFiles={resetDoneFiles}
                addFiles={addFiles}
                removeFile={removeFile}
                onAfterSend={handleAfterSend}
                onFocus={handleInputFocus}
                wasCommandBlocked={readOnlyNotice === null && wasCommandBlocked}
                isStopAvailable={isStopAvailable}
                isStopPending={isStopPending}
                onStopRequest={onStopRequest}
                inputActions={readOnlyNotice === null ? inputActions : []}
                editingMessageId={
                  readOnlyNotice === null
                    ? (editingMessage?.messageId ?? null)
                    : null
                }
                editingInitialValue={
                  readOnlyNotice === null
                    ? (editingMessage?.content ?? null)
                    : null
                }
                onCancelEdit={handleCancelEdit}
                editSendDisabled={editingMessage !== null && isResponsePending}
                inputDisabled={readOnlyNotice !== null}
                disabledPlaceholder={readOnlyNotice}
              />
            </Box>
          </Box>
        </Box>
      </Stack>
      <Box
        visibleFrom="lg"
        role="separator"
        aria-orientation="vertical"
        onPointerDown={handleWorkspaceResizeStart}
        h="100%"
        w={rem(10)}
        style={{
          cursor: "col-resize",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderLeft: `${rem(1)} solid var(--mantine-color-default-border)`,
        }}
      >
        <IconGripVertical size="1rem" color="var(--mantine-color-dimmed)" />
      </Box>
      <Box
        visibleFrom="lg"
        h="100%"
        style={{
          flex: `0 0 ${(1 - chatRatio) * 100}%`,
          minWidth: rem(320),
        }}
      >
        <WorkspacePanel {...workspacePanel} />
      </Box>
    </Group>
  );
}

export const ChatView = createReactContainer(
  "ChatView",
  useChatViewContainer,
  ChatViewPresentation,
);
