"use client";

/**
 * Chat-only draft screen shown before the first message creates an AgentSession.
 */

import {
  Alert,
  Anchor,
  Box,
  Center,
  Group,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import { IconMessageCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ChatInput } from "@/features/chat/components/ChatInput";
import { ComposerSubscriptionUsagePopoverContainer } from "@/features/chat/containers/ComposerSubscriptionUsageContainer";
import { WorkspaceDirectoryPickerModal } from "@/features/chat/workspace/components/WorkspaceDirectoryPickerModal";
import styles from "./AgentChatTab.module.css";
import { AgentSettingsHeader } from "./AgentSettingsHeader";
import { NewSessionProjectSelector } from "./NewSessionProjectSelector";
import { NewSessionScopeSelector } from "./NewSessionScopeSelector";
import type { AgentDraftChatContainerOutput } from "../containers/useAgentDraftChatContainer";

export function AgentDraftChat(
  props: AgentDraftChatContainerOutput,
): React.ReactElement {
  const {
    handle,
    agent,
    sessionScope,
    isWritePending,
    isInputUploading,
    isMobile,
    canSendMessage,
    pendingFiles,
    defaultInferenceProfile,
    subscriptionSelection,
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
    onSessionScopeChange,
    onSendInput,
    addFiles,
    removeFile,
    clearFiles,
    resetDoneFiles,
    uploadAll,
    onAfterSend,
    onStopRequest,
  } = props;
  const t = useTranslations("chat");

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
          <Group gap="xs" wrap="nowrap">
            <NewSessionScopeSelector
              value={sessionScope}
              onChange={onSessionScopeChange}
            />
            {subscriptionSelection === null ? null : (
              <ComposerSubscriptionUsagePopoverContainer
                compact
                handle={handle}
                integrationId={subscriptionSelection.integrationId}
                provider={subscriptionSelection.provider}
              />
            )}
          </Group>
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
          {agent.runtime_capability === "managed" ? (
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
          ) : (
            <Alert
              color={
                agent.runtime_capability === "removing" ? "yellow" : "blue"
              }
              mb="sm"
              title={
                agent.runtime_capability === "removing"
                  ? t("runtimeRemovingProjectTitle")
                  : t("runtimeFreeProjectTitle")
              }
            >
              <Text size="sm">
                {agent.runtime_capability === "removing"
                  ? t("runtimeRemovingProjectDescription")
                  : t.rich("runtimeFreeProjectDescription", {
                      runtimeLink: (chunks) => (
                        <Anchor
                          component={Link}
                          href={`/w/${handle}/agents/${agent.id}/settings/runtime`}
                        >
                          {chunks}
                        </Anchor>
                      ),
                    })}
              </Text>
            </Alert>
          )}
          <ChatInput
            agentId={agent.id}
            sessionId={null}
            isMobile={isMobile}
            isUploading={isInputUploading}
            pendingFiles={pendingFiles}
            goal={null}
            todo={null}
            uploadAll={uploadAll}
            selectableModelOptions={agent.selectable_model_options}
            defaultInferenceProfile={defaultInferenceProfile}
            onSendInput={onSendInput}
            clearFiles={clearFiles}
            resetDoneFiles={resetDoneFiles}
            addFiles={addFiles}
            removeFile={removeFile}
            onAfterSend={onAfterSend}
            wasCommandBlocked={false}
            isStopAvailable={false}
            isStopPending={false}
            onStopRequest={onStopRequest}
            inputActions={[]}
            editSendDisabled={isWritePending || !canSendMessage}
          />
        </Box>
      </Box>
      <WorkspaceDirectoryPickerModal
        opened={isProjectPickerOpen}
        state={projectPickerState}
        runtimeSettingsHref={`/w/${handle}/agents/${agent.id}/settings/runtime`}
        onClose={onCloseProjectPicker}
        onOpenDirectory={onOpenProjectPickerDirectory}
        onRefresh={onRefreshProjectPicker}
        onSelectDirectory={onSelectProjectPickerDirectory}
        onStartRuntime={onStartRuntimeForProjectPicker}
      />
    </Box>
  );
}
