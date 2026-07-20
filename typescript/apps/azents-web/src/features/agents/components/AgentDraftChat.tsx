"use client";

/**
 * Chat-only draft screen shown before the first message creates an AgentSession.
 */

import { Box, Center, rem, Stack, Text } from "@mantine/core";
import { IconMessageCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChatInput } from "@/features/chat/components/ChatInput";
import { resolveComposerSubscriptionSelection } from "@/features/chat/composerSubscriptionUsage";
import { ComposerSubscriptionUsagePopoverContainer } from "@/features/chat/containers/ComposerSubscriptionUsageContainer";
import { useFileUpload } from "@/features/chat/hooks/useFileUpload";
import { WorkspaceDirectoryPickerModal } from "@/features/chat/workspace/components/WorkspaceDirectoryPickerModal";
import styles from "./AgentChatTab.module.css";
import { AgentSettingsHeader } from "./AgentSettingsHeader";
import { NewSessionProjectSelector } from "./NewSessionProjectSelector";
import type { AgentDraftChatContainerOutput } from "../containers/useAgentDraftChatContainer";
import type { UploadedFile } from "@/features/chat/hooks/useFileUpload";
import type { RequestedInferenceProfile } from "@azents/public-client";

export function AgentDraftChat(
  props: AgentDraftChatContainerOutput,
): React.ReactElement {
  const {
    handle,
    agent,
    isWritePending,
    canSendMessage,
    onSendMessage,
    workspaceItems,
    activeWorktreeItemId,
    gitRefPreviewState,
    projectPresetState,
    projectPickerState,
    isProjectPickerOpen,
    onAddPresetProject,
    onSetWorkspaceItemKind,
    onActivateWorktreeItem,
    onSetWorktreeStartingRef,
    onRemoveWorkspaceItem,
    onOpenProjectPicker,
    onCloseProjectPicker,
    onOpenProjectPickerDirectory,
    onSelectProjectPickerDirectory,
    onRefreshProjectPicker,
    onStartRuntimeForProjectPicker,
  } = props;
  const t = useTranslations("chat");
  const isMobile = useMemo(
    () =>
      typeof window !== "undefined" &&
      ("ontouchstart" in window || navigator.maxTouchPoints > 0),
    [],
  );
  const {
    pendingFiles,
    addFiles,
    removeFile,
    clearFiles,
    resetDoneFiles,
    uploadAll,
    isUploading,
  } = useFileUpload();

  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    const previousRootOverflow = root.style.overflow;
    const previousRootOverscrollBehavior = root.style.overscrollBehavior;
    const previousBodyOverflow = body.style.overflow;
    const previousBodyOverscrollBehavior = body.style.overscrollBehavior;

    root.style.overflow = "hidden";
    root.style.overscrollBehavior = "none";
    body.style.overflow = "hidden";
    body.style.overscrollBehavior = "none";

    return () => {
      root.style.overflow = previousRootOverflow;
      root.style.overscrollBehavior = previousRootOverscrollBehavior;
      body.style.overflow = previousBodyOverflow;
      body.style.overscrollBehavior = previousBodyOverscrollBehavior;
    };
  }, []);

  const defaultInferenceProfile = useMemo<RequestedInferenceProfile>(
    () => ({
      model_target_label: agent.main_model_label,
      reasoning_effort: agent.model_parameters?.reasoning_effort ?? null,
    }),
    [agent.main_model_label, agent.model_parameters?.reasoning_effort],
  );
  const [composerInferenceProfileState, setComposerInferenceProfileState] =
    useState<{
      agentId: string;
      profile: RequestedInferenceProfile;
    }>(() => ({
      agentId: agent.id,
      profile: defaultInferenceProfile,
    }));
  const composerInferenceProfile =
    composerInferenceProfileState.agentId === agent.id
      ? composerInferenceProfileState.profile
      : defaultInferenceProfile;
  const handleComposerInferenceProfileChange = useCallback(
    (profile: RequestedInferenceProfile): void => {
      setComposerInferenceProfileState((current) => {
        if (
          current.agentId === agent.id &&
          current.profile.model_target_label === profile.model_target_label &&
          current.profile.reasoning_effort === profile.reasoning_effort
        ) {
          return current;
        }
        return { agentId: agent.id, profile };
      });
    },
    [agent.id],
  );
  const subscriptionSelection = useMemo(
    () =>
      resolveComposerSubscriptionSelection(
        agent.selectable_model_options,
        composerInferenceProfile.model_target_label,
      ),
    [
      agent.selectable_model_options,
      composerInferenceProfile.model_target_label,
    ],
  );

  const handleSendMessage = useCallback(
    async (
      message: string,
      inferenceProfile: RequestedInferenceProfile,
      attachments?: UploadedFile[],
    ): Promise<boolean> => {
      return onSendMessage(message, inferenceProfile, attachments);
    },
    [onSendMessage],
  );

  const handleAfterSend = useCallback((): void => {}, []);

  return (
    <Box
      className={styles.chatArea}
      style={{
        flex: 1,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <AgentSettingsHeader
        agent={agent}
        controls={
          subscriptionSelection === null ? null : (
            <ComposerSubscriptionUsagePopoverContainer
              compact
              handle={handle}
              integrationId={subscriptionSelection.integrationId}
              provider={subscriptionSelection.provider}
            />
          )
        }
      />
      <Center flex={1} mih={0} px="md">
        <Stack align="center" gap="sm">
          <IconMessageCircle size={48} color="var(--mantine-color-dimmed)" />
          <Text fw={600} size="lg" ta="center">
            {agent.name}
          </Text>
          <Text c="dimmed" size="sm" ta="center">
            {t("startConversation")}
          </Text>
        </Stack>
      </Center>
      <Box px="md" py="sm" style={{ flexShrink: 0 }}>
        <Box maw={rem(920)} mx="auto">
          <NewSessionProjectSelector
            activeWorktreeItemId={activeWorktreeItemId}
            gitRefPreviewState={gitRefPreviewState}
            projectPresetState={projectPresetState}
            workspaceItems={workspaceItems}
            onActivateWorktreeItem={onActivateWorktreeItem}
            onAddPresetProject={onAddPresetProject}
            onOpenProjectPicker={onOpenProjectPicker}
            onSetWorkspaceItemKind={onSetWorkspaceItemKind}
            onRemoveWorkspaceItem={onRemoveWorkspaceItem}
            onSetWorktreeStartingRef={onSetWorktreeStartingRef}
          />
          <ChatInput
            agentId={agent.id}
            sessionId={null}
            isMobile={isMobile}
            isUploading={isUploading || isWritePending}
            pendingFiles={pendingFiles}
            goal={null}
            todo={null}
            uploadAll={uploadAll}
            selectableModelOptions={agent.selectable_model_options}
            defaultInferenceProfile={defaultInferenceProfile}
            onInferenceProfileChange={handleComposerInferenceProfileChange}
            onSendInput={(message, action, inferenceProfile, attachments) =>
              action
                ? Promise.resolve(false)
                : handleSendMessage(message, inferenceProfile, attachments)
            }
            clearFiles={clearFiles}
            resetDoneFiles={resetDoneFiles}
            addFiles={addFiles}
            removeFile={removeFile}
            onAfterSend={handleAfterSend}
            wasCommandBlocked={false}
            isStopAvailable={false}
            isStopPending={false}
            onStopRequest={() => {}}
            inputActions={[]}
            editSendDisabled={isWritePending || !canSendMessage}
          />
        </Box>
      </Box>
      <WorkspaceDirectoryPickerModal
        opened={isProjectPickerOpen}
        state={projectPickerState}
        onClose={onCloseProjectPicker}
        onOpenDirectory={onOpenProjectPickerDirectory}
        onRefresh={onRefreshProjectPicker}
        onSelectDirectory={onSelectProjectPickerDirectory}
        onStartRuntime={onStartRuntimeForProjectPicker}
      />
    </Box>
  );
}
