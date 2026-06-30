"use client";

/**
 * Chat-only draft screen shown before the first message creates an AgentSession.
 */

import { Box, Center, rem, Stack, Text } from "@mantine/core";
import { IconMessageCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo } from "react";
import { ChatInput } from "@/features/chat/components/ChatInput";
import { useFileUpload } from "@/features/chat/hooks/useFileUpload";
import { WorkspaceDirectoryPickerModal } from "@/features/chat/workspace/components/WorkspaceDirectoryPickerModal";
import styles from "./AgentChatTab.module.css";
import { AgentSettingsHeader } from "./AgentSettingsHeader";
import { NewSessionProjectSelector } from "./NewSessionProjectSelector";
import type { AgentDraftChatContainerOutput } from "../containers/useAgentDraftChatContainer";
import type { UploadedFile } from "@/features/chat/hooks/useFileUpload";

export function AgentDraftChat(
  props: AgentDraftChatContainerOutput,
): React.ReactElement {
  const {
    agent,
    isWritePending,
    onSendMessage,
    selectedProjectPaths,
    projectPresetState,
    projectPickerState,
    isProjectPickerOpen,
    onAddPresetProject,
    onRemoveProject,
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
    clearDoneFiles,
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

  const handleSendMessage = useCallback(
    async (message: string, attachments?: UploadedFile[]): Promise<boolean> => {
      return onSendMessage(message, attachments);
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
      <AgentSettingsHeader agent={agent} />
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
            projectPresetState={projectPresetState}
            selectedProjectPaths={selectedProjectPaths}
            onAddPresetProject={onAddPresetProject}
            onOpenProjectPicker={onOpenProjectPicker}
            onRemoveProject={onRemoveProject}
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
            onSendInput={(message, action, attachments) =>
              action
                ? Promise.resolve(false)
                : handleSendMessage(message, attachments)
            }
            clearDoneFiles={clearDoneFiles}
            resetDoneFiles={resetDoneFiles}
            addFiles={addFiles}
            removeFile={removeFile}
            onAfterSend={handleAfterSend}
            wasCommandBlocked={false}
            isStopAvailable={false}
            isStopPending={false}
            onStopRequest={() => {}}
            inputActions={[]}
            editSendDisabled={isWritePending}
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
