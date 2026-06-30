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
import type { PendingFile, UploadedFile } from "../hooks/useFileUpload";
import type {
  ChatAction,
  GoalStateSnapshot,
  InputActionDefinition,
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
  /** input send callback */
  onSendInput: (
    message: string,
    action?: ChatAction | null,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** clear attached file draft state */
  clearFiles: () => void;
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
  /** server-managed input action list */
  inputActions: InputActionDefinition[];
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

function actionType(action: InputActionDefinition["action"]): string | null {
  return typeof action.type === "string" ? action.type : null;
}

function normalizeAction(
  action: InputActionDefinition["action"],
): ChatAction | null {
  const type = actionType(action);
  if (
    type === "command" &&
    "name" in action &&
    typeof action.name === "string"
  ) {
    return { type: "command", name: action.name };
  }
  if (type === "goal") {
    return { type: "goal" };
  }
  if (
    type === "skill" &&
    "skill_id" in action &&
    typeof action.skill_id === "string"
  ) {
    return { type: "skill", skill_id: action.skill_id };
  }
  return null;
}

function getInputActionQuery(inputValue: string): string | null {
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

interface ComposerDraft {
  message: string;
  action: ChatAction | null;
}

interface RankedInputAction {
  action: InputActionDefinition;
  score: number;
  ranges: number[];
}

function normalizeStoredAction(value: unknown): ChatAction | null {
  if (typeof value !== "object" || value === null || !("type" in value)) {
    return null;
  }
  const action = value as Record<string, unknown>;
  if (action.type === "command" && typeof action.name === "string") {
    return { type: "command", name: action.name };
  }
  if (action.type === "goal") {
    return { type: "goal" };
  }
  if (action.type === "skill" && typeof action.skill_id === "string") {
    return { type: "skill", skill_id: action.skill_id };
  }
  return null;
}

function parseComposerDraft(raw: string): ComposerDraft {
  if (!raw) {
    return { message: "", action: null };
  }
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value === "object" && value !== null && "message" in value) {
      const record = value as Record<string, unknown>;
      return {
        message: typeof record.message === "string" ? record.message : "",
        action: normalizeStoredAction(record.action),
      };
    }
  } catch {
    // Legacy drafts were stored as plain message strings.
  }
  return { message: raw, action: null };
}

function serializeComposerDraft(
  message: string,
  action: ChatAction | null,
): string {
  if (!message && action === null) {
    return "";
  }
  return JSON.stringify({ message, action });
}

function actionKey(action: ChatAction | null): string {
  return JSON.stringify(action);
}

function fallbackActionDefinition(action: ChatAction): InputActionDefinition {
  switch (action.type) {
    case "command":
      return {
        id: `command:${action.name}`,
        keyword: action.name,
        label: action.name,
        description: "",
        action,
        category: "command",
        message: { policy: "optional", placeholder: null, max_length: null },
        attachments: { policy: "unsupported" },
        availability_hint: null,
      };
    case "goal":
      return {
        id: "goal",
        keyword: "goal",
        label: "Goal",
        description: "",
        action,
        category: "turn",
        message: { policy: "required", placeholder: null, max_length: 4000 },
        attachments: { policy: "unsupported" },
        availability_hint: null,
      };
    case "skill":
      return {
        id: `skill:${action.skill_id}`,
        keyword: "skill",
        label: "Skill",
        description: "",
        action,
        category: "turn",
        message: { policy: "optional", placeholder: null, max_length: null },
        attachments: { policy: "optional" },
        availability_hint: null,
      };
  }
}

function resolveActionDefinition(
  action: ChatAction | null,
  inputActions: InputActionDefinition[],
): InputActionDefinition | null {
  if (action === null) {
    return null;
  }
  const key = actionKey(action);
  return (
    inputActions.find(
      (definition) => actionKey(normalizeAction(definition.action)) === key,
    ) ?? fallbackActionDefinition(action)
  );
}

function rankInputAction(
  action: InputActionDefinition,
  query: string,
): RankedInputAction | null {
  const keyword = action.keyword.toLowerCase();
  if (query === "") {
    return { action, score: 1, ranges: [] };
  }
  if (keyword === query) {
    return { action, score: 0, ranges: [...query].map((_, index) => index) };
  }
  if (keyword.startsWith(query)) {
    return { action, score: 1, ranges: [...query].map((_, index) => index) };
  }
  const containsIndex = keyword.indexOf(query);
  if (containsIndex >= 0) {
    return {
      action,
      score: 2,
      ranges: [...query].map((_, index) => containsIndex + index),
    };
  }
  const ranges: number[] = [];
  let cursor = 0;
  for (const char of query) {
    const index = keyword.indexOf(char, cursor);
    if (index < 0) {
      return null;
    }
    ranges.push(index);
    cursor = index + 1;
  }
  return { action, score: 3, ranges };
}

function HighlightedKeyword({
  keyword,
  ranges,
}: {
  keyword: string;
  ranges: number[];
}): React.ReactElement {
  const highlighted = new Set(ranges);
  return (
    <>
      /
      {[...keyword].map((char, index) => (
        <Text
          key={`${char}-${index}`}
          component="span"
          inherit
          fw={highlighted.has(index) ? 800 : 500}
          td={highlighted.has(index) ? "underline" : void 0}
        >
          {char}
        </Text>
      ))}
    </>
  );
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
  onSendInput,
  clearFiles,
  resetDoneFiles,
  addFiles,
  removeFile,
  onAfterSend,
  onFocus,
  wasCommandBlocked,
  isStopAvailable,
  isStopPending,
  onStopRequest,
  inputActions,
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
  const parsedDraft = useMemo(
    () => parseComposerDraft(draftValue),
    [draftValue],
  );
  const [inputValue, setInputValue] = useState(
    initialInputValue ?? parsedDraft.message,
  );
  const [sendErrorVisible, setSendErrorVisible] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const [selectedAction, setSelectedAction] =
    useState<InputActionDefinition | null>(() =>
      resolveActionDefinition(parsedDraft.action, inputActions),
    );
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const previousEditingMessageIdRef = useRef<string | null>(null);
  const inputActionQuery = selectedAction
    ? null
    : getInputActionQuery(inputValue);
  const visibleInputActions = useMemo(() => {
    if (inputActionQuery === null) {
      return [];
    }
    return inputActions
      .flatMap((action) => {
        const ranked = rankInputAction(action, inputActionQuery);
        return ranked === null ? [] : [ranked];
      })
      .sort(
        (a, b) =>
          a.score - b.score || a.action.keyword.localeCompare(b.action.keyword),
      );
  }, [inputActionQuery, inputActions]);

  useEffect(() => {
    if (editingMessageId !== null) {
      return;
    }
    if (initialInputValue !== void 0) {
      setInputValue(initialInputValue);
      setSelectedAction(null);
      return;
    }
    setInputValue(parsedDraft.message);
    setSelectedAction(
      resolveActionDefinition(parsedDraft.action, inputActions),
    );
  }, [editingMessageId, initialInputValue, inputActions, parsedDraft]);

  useEffect(() => {
    if (selectedAction === null) {
      return;
    }
    const resolved = resolveActionDefinition(
      normalizeAction(selectedAction.action),
      inputActions,
    );
    if (
      resolved !== null &&
      (resolved.id !== selectedAction.id ||
        resolved.description !== selectedAction.description ||
        resolved.availability_hint?.message !==
          selectedAction.availability_hint?.message)
    ) {
      setSelectedAction(resolved);
    }
  }, [inputActions, selectedAction]);

  const clearDraft = useCallback((): void => {
    clearStoredDraft();
  }, [clearStoredDraft]);

  const persistDraft = useCallback(
    (message: string, action: ChatAction | null): void => {
      if (editingMessageId !== null || !draftStorageKey) {
        return;
      }
      const serialized = serializeComposerDraft(message, action);
      if (serialized === "") {
        clearStoredDraft();
        return;
      }
      setDraftValue(serialized);
    },
    [clearStoredDraft, draftStorageKey, editingMessageId, setDraftValue],
  );

  const updateInputValue = useCallback(
    (nextValue: string): void => {
      setSendErrorVisible(false);
      setInputValue(nextValue);
      persistDraft(
        nextValue,
        selectedAction === null ? null : normalizeAction(selectedAction.action),
      );
    },
    [persistDraft, selectedAction],
  );

  useEffect(() => {
    if (editingMessageId !== previousEditingMessageIdRef.current) {
      previousEditingMessageIdRef.current = editingMessageId;
      if (editingMessageId !== null) {
        setSelectedAction(null);
        setInputValue(editingInitialValue ?? "");
        textareaRef.current?.focus();
      }
    }
  }, [editingInitialValue, editingMessageId]);

  const handleCancelEdit = useCallback(() => {
    setInputValue("");
    setSelectedAction(null);
    clearDraft();
    previousEditingMessageIdRef.current = null;
    onCancelEdit?.();
  }, [clearDraft, onCancelEdit]);

  const clearInputAfterSend = useCallback((): void => {
    setSendErrorVisible(false);
    setSelectedAction(null);
    updateInputValue("");
    clearDraft();
    clearFiles();
    onAfterSend();
  }, [clearDraft, clearFiles, onAfterSend, updateInputValue]);

  const handleSend = useCallback((): void => {
    const send = async (): Promise<void> => {
      const trimmed = inputValue.trim();
      const normalizedAction =
        selectedAction === null ? null : normalizeAction(selectedAction.action);
      if (isUploading || editSendDisabled) {
        return;
      }

      const hasAttachedFiles = pendingFiles.length > 0;
      const messagePolicy = selectedAction?.message.policy ?? "required";
      const attachmentPolicy = selectedAction?.attachments.policy ?? "optional";
      if (!trimmed && !hasAttachedFiles && messagePolicy === "required") {
        return;
      }
      if (hasAttachedFiles && attachmentPolicy === "unsupported") {
        setSendErrorVisible(true);
        return;
      }
      if (!hasAttachedFiles && attachmentPolicy === "required") {
        setSendErrorVisible(true);
        return;
      }

      // file attachment existstextwhen Agent based on with upload after send.
      if (hasAttachedFiles) {
        if (!agentId) {
          return;
        }
        try {
          const uploaded = await uploadAll(agentId);
          if (uploaded.length === 0) {
            if (!trimmed || attachmentPolicy === "required") {
              setSendErrorVisible(true);
              resetDoneFiles();
              return;
            }
            clearFiles();
            const sentWithoutAttachments = await onSendInput(
              trimmed,
              normalizedAction,
            );
            if (sentWithoutAttachments) {
              clearInputAfterSend();
            } else {
              setSendErrorVisible(true);
            }
            return;
          }
          const sent = await onSendInput(trimmed, normalizedAction, uploaded);
          if (sent) {
            clearInputAfterSend();
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

      const sent = await onSendInput(trimmed, normalizedAction);
      if (sent) {
        clearInputAfterSend();
      } else {
        setSendErrorVisible(true);
      }
    };
    void send();
  }, [
    inputValue,
    selectedAction,
    isUploading,
    editSendDisabled,
    pendingFiles,
    agentId,
    uploadAll,
    onSendInput,
    clearInputAfterSend,
    clearFiles,
    resetDoneFiles,
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

  const handleTextareaFocus = useCallback((): void => {
    setComposerFocused(true);
    onFocus?.();
  }, [onFocus]);

  const handleComposerBlur = useCallback(
    (event: React.FocusEvent<HTMLDivElement>): void => {
      if (event.currentTarget.contains(event.relatedTarget)) {
        return;
      }
      setComposerFocused(false);
    },
    [],
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

  const handleSelectInputAction = useCallback(
    (definition: InputActionDefinition): void => {
      const normalizedAction = normalizeAction(definition.action);
      if (normalizedAction === null) {
        return;
      }
      setSelectedAction(definition);
      setInputValue("");
      persistDraft("", normalizedAction);
      textareaRef.current?.focus();
    },
    [persistDraft],
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
            {selectedAction
              ? `${selectedAction.label} action failed. Edit it or try again.`
              : "Message failed to send. Try again."}
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
        {visibleInputActions.length > 0 && (
          <Paper withBorder radius="md" p="xs">
            <Stack gap={rem(2)}>
              <Text size="xs" c="dimmed" px="xs">
                {t("slashCommands.title")}
              </Text>
              {visibleInputActions.map((ranked) => (
                <UnstyledButton
                  key={ranked.action.id}
                  onClick={() => handleSelectInputAction(ranked.action)}
                  px="xs"
                  py={rem(6)}
                  style={{ borderRadius: rem(8), width: "100%" }}
                >
                  <Stack gap={rem(2)}>
                    <Group justify="space-between" gap="sm" wrap="nowrap">
                      <Text size="sm" fw={500}>
                        <HighlightedKeyword
                          keyword={ranked.action.keyword}
                          ranges={ranked.ranges}
                        />
                      </Text>
                      <Text size="xs" c="dimmed" ta="right">
                        {ranked.action.description}
                      </Text>
                    </Group>
                    {ranked.action.availability_hint?.message && (
                      <Text size="xs" c="orange" ta="right">
                        {ranked.action.availability_hint.message}
                      </Text>
                    )}
                  </Stack>
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
            disabled={
              isUploading ||
              Boolean(editingMessageId) ||
              selectedAction?.attachments.policy === "unsupported"
            }
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
              <Paper
                withBorder
                radius="md"
                px="sm"
                py={rem(6)}
                onBlur={handleComposerBlur}
                onClick={() => textareaRef.current?.focus()}
                style={{
                  borderColor: composerFocused
                    ? "var(--mantine-color-blue-5)"
                    : void 0,
                  boxShadow: composerFocused
                    ? "0 0 0 1px var(--mantine-color-blue-5)"
                    : void 0,
                  transition: "border-color 120ms ease, box-shadow 120ms ease",
                }}
              >
                <Stack gap={rem(4)}>
                  {selectedAction !== null && !editingMessageId && (
                    <Stack gap={rem(2)} align="flex-start">
                      <Group
                        gap={rem(4)}
                        wrap="nowrap"
                        px={rem(8)}
                        py={rem(3)}
                        style={{
                          borderRadius: rem(999),
                          background: "var(--mantine-color-blue-light)",
                          border:
                            "1px solid var(--mantine-color-blue-light-color)",
                          width: "fit-content",
                          maxWidth: "100%",
                        }}
                      >
                        <Text size="xs" fw={700} c="blue" truncate>
                          /{selectedAction.keyword}
                        </Text>
                        <ActionIcon
                          variant="transparent"
                          size={rem(16)}
                          c="dimmed"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedAction(null);
                            persistDraft(inputValue, null);
                            textareaRef.current?.focus();
                          }}
                          aria-label={t("cancelEdit")}
                        >
                          <IconX size={12} />
                        </ActionIcon>
                      </Group>
                      {selectedAction.availability_hint?.message && (
                        <Text size="xs" c="orange" pl={rem(2)}>
                          {selectedAction.availability_hint.message}
                        </Text>
                      )}
                    </Stack>
                  )}
                  <Box style={{ minWidth: 0, position: "relative" }}>
                    {todo !== null &&
                      !editingMessageId &&
                      selectedAction === null &&
                      inputActionQuery === null && (
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
                      variant="unstyled"
                      placeholder={
                        selectedAction?.message.placeholder ??
                        (isMobile
                          ? t("inputPlaceholder")
                          : t("inputPlaceholderDesktop"))
                      }
                      value={inputValue}
                      onChange={(e) => updateInputValue(e.currentTarget.value)}
                      onKeyDown={handleKeyDown}
                      onFocus={handleTextareaFocus}
                      autosize
                      minRows={1}
                      maxRows={5}
                      flex={1}
                      styles={{
                        input: {
                          fontSize: rem(16),
                          padding: 0,
                          minHeight: rem(28),
                        },
                      }}
                    />
                  </Box>
                </Stack>
              </Paper>
            </Stack>
          </Box>
          {isStopAvailable && !inputValue.trim() && selectedAction === null ? (
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
              disabled={
                editSendDisabled ||
                (!inputValue.trim() &&
                  selectedAction?.message.policy === "required")
              }
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
