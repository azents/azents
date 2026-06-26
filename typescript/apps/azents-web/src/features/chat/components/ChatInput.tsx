"use client";

/**
 * chat input component.
 *
 * inputValue status internally with manage input when parent(ChatView) entire
 * is not rerendered on input.
 */

import {
  ActionIcon,
  Box,
  Group,
  Paper,
  rem,
  Stack,
  Text,
  Textarea,
  UnstyledButton,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import {
  IconPaperclip,
  IconPlayerStop,
  IconSend,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AttachmentPreviewBar } from "./AttachmentPreviewBar";
import { TodoPreviewBar } from "./TodoPreviewBar";
import type { UploadedFile } from "../hooks/useFileUpload";
import type { PendingFile } from "../hooks/useFileUpload";
import type {
  GoalStateSnapshot,
  SlashCommand,
  TodoStateSnapshot,
} from "../types";

const DRAFT_STORAGE_KEY_PREFIX = "azents.chat.inputDraft";

function getDraftStorageKey(
  agentId: string | null,
  sessionId: string | null,
): string | null {
  if (!agentId) {
    return null;
  }
  return `${DRAFT_STORAGE_KEY_PREFIX}.${agentId}.${sessionId ?? "new"}`;
}

interface ChatInputProps {
  /** current agent ID */
  agentId: string | null;
  /** current session ID */
  sessionId: string | null;
  /** whether mobile */
  isMobile: boolean;
  /** file whether uploading */
  isUploading: boolean;
  /** pending file list */
  pendingFiles: PendingFile[];
  /** to attach and show on input goal snapshot */
  goal: GoalStateSnapshot | null;
  /** to attach and show on input todo snapshot */
  todo: TodoStateSnapshot | null;
  /** Goal delete callback */
  onClearGoal?: () => Promise<boolean>;
  /** Goal update callback */
  onUpdateGoal?: (objective: string) => Promise<boolean>;
  /** Goal pause callback */
  onPauseGoal?: () => Promise<boolean>;
  /** Goal resume callback */
  onResumeGoal?: (hint?: string) => Promise<boolean>;
  /** file upload function */
  uploadAll: (agentId: string) => Promise<UploadedFile[]>;
  /** message send callback */
  onSendMessage: (
    message: string,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** send command selected from slash autocomplete */
  onSendCommand: (command: string) => Promise<boolean>;
  /** complete file clear */
  clearDoneFiles: () => void;
  /** complete file status pending  with text. */
  resetDoneFiles: () => void;
  /** file add callback */
  addFiles: (files: FileList) => void;
  /** file remove callback */
  removeFile: (id: string) => void;
  /** scroll callback after send */
  onAfterSend: () => void;
  /** inputinput scroll adjustment callback on focus */
  onFocus?: () => void;
  /** whether commands are blocked during Run */
  wasCommandBlocked: boolean;
  /** Session run_state based on stop button exposed whether */
  isStopAvailable: boolean;
  /** whether stop request is being sent */
  isStopPending: boolean;
  /** run stop request callback */
  onStopRequest: () => void;
  /** server-managed textwhen text list */
  slashCommands: SlashCommand[];
  /** Storybook etc. in used to inject initial input value */
  initialInputValue?: string;
  /** currently edited message ID */
  editingMessageId?: string | null;
  /** value to copy into input when editing starts */
  editingInitialValue?: string | null;
  /** cancel editing */
  onCancelEdit?: () => void;
  /** whether edit send is blocked by external run, etc. */
  editSendDisabled?: boolean;
}

function getSlashCommandQuery(inputValue: string): string | null {
  const trimmedStart = inputValue.trimStart();
  if (!trimmedStart.startsWith("/")) {
    return null;
  }

  const commandSegment = trimmedStart.slice(1);
  if (commandSegment.includes(" ")) {
    return null;
  }

  return commandSegment.toLowerCase();
}

export const ChatInput = memo(function ChatInput({
  agentId,
  sessionId,
  isMobile,
  isUploading,
  pendingFiles,
  goal,
  todo,
  onClearGoal,
  onUpdateGoal,
  onPauseGoal,
  onResumeGoal,
  uploadAll,
  onSendMessage,
  onSendCommand,
  clearDoneFiles,
  resetDoneFiles,
  addFiles,
  removeFile,
  onAfterSend,
  onFocus,
  wasCommandBlocked,
  isStopAvailable,
  isStopPending,
  onStopRequest,
  slashCommands,
  initialInputValue,
  editingMessageId = null,
  editingInitialValue = null,
  onCancelEdit,
  editSendDisabled = false,
}: ChatInputProps): React.ReactElement {
  const t = useTranslations("chat");
  const draftStorageKey = useMemo(
    () => getDraftStorageKey(agentId, sessionId),
    [agentId, sessionId],
  );
  const storageKey =
    draftStorageKey ?? `${DRAFT_STORAGE_KEY_PREFIX}.__disabled`;
  const [draftValue, setDraftValue, clearStoredDraft] = useLocalStorage<string>(
    {
      key: storageKey,
      defaultValue: "",
    },
  );
  const [inputValue, setInputValue] = useState(initialInputValue ?? draftValue);
  const [sendErrorVisible, setSendErrorVisible] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const previousEditingMessageIdRef = useRef<string | null>(null);
  const slashCommandQuery = getSlashCommandQuery(inputValue);
  const visibleSlashCommands =
    slashCommandQuery === null
      ? []
      : slashCommands.filter((command) =>
          command.name.toLowerCase().startsWith(slashCommandQuery),
        );

  useEffect(() => {
    if (editingMessageId !== null) {
      return;
    }
    if (typeof initialInputValue !== "undefined") {
      setInputValue(initialInputValue);
      return;
    }
    setInputValue(draftValue);
  }, [draftValue, editingMessageId, initialInputValue]);

  const clearDraft = useCallback((): void => {
    clearStoredDraft();
  }, [clearStoredDraft]);

  const updateInputValue = useCallback(
    (nextValue: string): void => {
      setSendErrorVisible(false);
      setInputValue(nextValue);
      if (editingMessageId !== null) {
        return;
      }
      if (!draftStorageKey) {
        return;
      }
      if (nextValue === "") {
        clearStoredDraft();
        return;
      }
      setDraftValue(nextValue);
    },
    [clearStoredDraft, draftStorageKey, editingMessageId, setDraftValue],
  );

  useEffect(() => {
    if (editingMessageId !== previousEditingMessageIdRef.current) {
      previousEditingMessageIdRef.current = editingMessageId;
      if (editingMessageId !== null) {
        setInputValue(editingInitialValue ?? "");
        textareaRef.current?.focus();
      }
    }
  }, [editingInitialValue, editingMessageId]);

  const handleCancelEdit = useCallback(() => {
    setInputValue("");
    clearDraft();
    previousEditingMessageIdRef.current = null;
    onCancelEdit?.();
  }, [clearDraft, onCancelEdit]);

  const handleSend = useCallback((): void => {
    const send = async (): Promise<void> => {
      const trimmed = inputValue.trim();
      if (!trimmed || isUploading || editSendDisabled) {
        return;
      }

      const hasAttachedFiles = pendingFiles.length > 0;

      // file attachment existstextwhen Agent based on with upload after send.
      if (hasAttachedFiles) {
        if (!agentId) {
          return;
        }
        try {
          const uploaded = await uploadAll(agentId);
          if (uploaded.length === 0) {
            return;
          }
          const sent = await onSendMessage(trimmed, uploaded);
          if (sent) {
            setSendErrorVisible(false);
            updateInputValue("");
            clearDraft();
            clearDoneFiles();
            onAfterSend();
          } else {
            setSendErrorVisible(true);
            resetDoneFiles();
          }
        } catch {
          setSendErrorVisible(true);
          resetDoneFiles();
        }
        return;
      }

      const sent = await onSendMessage(trimmed);
      if (sent) {
        setSendErrorVisible(false);
        updateInputValue("");
        clearDraft();
        onAfterSend();
      } else {
        setSendErrorVisible(true);
      }
    };
    void send();
  }, [
    inputValue,
    isUploading,
    editSendDisabled,
    pendingFiles,
    agentId,
    uploadAll,
    onSendMessage,
    clearDoneFiles,
    resetDoneFiles,
    onAfterSend,
    clearDraft,
    updateInputValue,
  ]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // mobile in Enter with textrow, text button withonly send
      if (isMobile) {
        return;
      }
      // Ignore Enter during IME input (Korean, etc.) — handle after compositionend.
      if (e.nativeEvent.isComposing) {
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend, isMobile],
  );

  /** file select handler */
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        addFiles(e.target.files);
      }
      // input value sectext (text file textselect textalsotext)
      e.target.value = "";
    },
    [addFiles],
  );

  const handleSelectSlashCommand = useCallback(
    (commandName: string): void => {
      const send = async (): Promise<void> => {
        if (isUploading || editSendDisabled || pendingFiles.length > 0) {
          return;
        }
        const sent = await onSendCommand(commandName);
        if (!sent) {
          setSendErrorVisible(true);
          textareaRef.current?.focus();
          return;
        }
        setSendErrorVisible(false);
        updateInputValue("");
        clearDraft();
        onAfterSend();
      };
      void send();
    },
    [
      clearDraft,
      editSendDisabled,
      isUploading,
      onAfterSend,
      onSendCommand,
      pendingFiles.length,
      updateInputValue,
    ],
  );

  return (
    <>
      {/* hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        style={{ display: "none" }}
        onChange={handleFileChange}
      />
      {/* command blocked notice during Run */}
      {wasCommandBlocked && (
        <Text size="xs" c="orange" mb={4}>
          {t("commandBlockedDuringRun")}
        </Text>
      )}
      <Stack gap="xs">
        {sendErrorVisible && (
          <Text size="xs" c="red">
            Message failed to send. Try again.
          </Text>
        )}
        {editingMessageId && (
          <Paper withBorder radius="sm" px="sm" py="2xs">
            <Group justify="space-between" gap="sm" wrap="nowrap">
              <Text size="xs" c="dimmed" fw={500}>
                {editSendDisabled
                  ? t("editBlockedDuringRun")
                  : t("editingMessage")}
              </Text>
              <ActionIcon
                variant="subtle"
                size="sm"
                c="dimmed"
                onClick={handleCancelEdit}
                aria-label={t("cancelEdit")}
              >
                <IconX size={14} />
              </ActionIcon>
            </Group>
          </Paper>
        )}
        {visibleSlashCommands.length > 0 && (
          <Paper withBorder radius="md" p="xs">
            <Stack gap={rem(2)}>
              <Text size="xs" c="dimmed" px="xs">
                {t("slashCommands.title")}
              </Text>
              {visibleSlashCommands.map((command) => (
                <UnstyledButton
                  key={command.name}
                  onClick={() => handleSelectSlashCommand(command.name)}
                  px="xs"
                  py={rem(6)}
                  style={{ borderRadius: rem(8) }}
                >
                  <Group justify="space-between" gap="sm" wrap="nowrap">
                    <Text size="sm" fw={500}>
                      /{command.name}
                    </Text>
                    <Text size="xs" c="dimmed" ta="right">
                      {command.description}
                    </Text>
                  </Group>
                </UnstyledButton>
              ))}
            </Stack>
          </Paper>
        )}
        <Group align="flex-end" gap="xs">
          <ActionIcon
            size="input-sm"
            variant="subtle"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading || Boolean(editingMessageId)}
            aria-label={t("attachment.attach")}
          >
            <IconPaperclip size={18} />
          </ActionIcon>
          <Box flex={1} style={{ minWidth: 0 }}>
            <Stack gap={rem(4)}>
              {pendingFiles.length > 0 && !editingMessageId && (
                <AttachmentPreviewBar
                  pendingFiles={pendingFiles}
                  onRemove={removeFile}
                />
              )}
              <Box style={{ minWidth: 0, position: "relative" }}>
                {todo !== null && !editingMessageId && (
                  <TodoPreviewBar
                    goal={goal}
                    isMobile={isMobile}
                    todo={todo}
                    onClearGoal={onClearGoal}
                    onUpdateGoal={onUpdateGoal}
                    onPauseGoal={onPauseGoal}
                    onResumeGoal={onResumeGoal}
                  />
                )}
                <Textarea
                  ref={textareaRef}
                  placeholder={
                    isMobile
                      ? t("inputPlaceholder")
                      : t("inputPlaceholderDesktop")
                  }
                  value={inputValue}
                  onChange={(e) => updateInputValue(e.currentTarget.value)}
                  onKeyDown={handleKeyDown}
                  onFocus={onFocus}
                  autosize
                  minRows={1}
                  maxRows={5}
                  flex={1}
                  styles={{ input: { fontSize: rem(16) } }}
                />
              </Box>
            </Stack>
          </Box>
          {isStopAvailable && !inputValue.trim() ? (
            <ActionIcon
              size="input-sm"
              variant="filled"
              color="red"
              onClick={onStopRequest}
              onMouseDown={(e) => e.preventDefault()}
              loading={isStopPending}
              aria-label={t("stopRun")}
            >
              <IconPlayerStop size={18} />
            </ActionIcon>
          ) : (
            <ActionIcon
              size="input-sm"
              variant="filled"
              onClick={handleSend}
              onMouseDown={(e) => e.preventDefault()}
              disabled={!inputValue.trim() || editSendDisabled}
              loading={isUploading}
            >
              <IconSend size={18} />
            </ActionIcon>
          )}
        </Group>
      </Stack>
    </>
  );
});
