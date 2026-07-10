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
  Button,
  Drawer,
  Group,
  Paper,
  rem,
  Select,
  Stack,
  Text,
  Textarea,
  UnstyledButton,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import {
  IconAdjustmentsHorizontal,
  IconChevronDown,
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
import type {
  AgentResponse,
  ModelReasoningEffort,
  RequestedInferenceProfile,
} from "@azents/public-client";

const DRAFT_STORAGE_KEY_PREFIX = "azents.chat.inputDraft";
const ALL_REASONING_EFFORTS: ModelReasoningEffort[] = ["low", "medium", "high"];

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
  /** Agent-owned selectable model targets */
  selectableModelOptions: AgentResponse["selectable_model_options"];
  /** profile restored from durable/session/Agent state */
  defaultInferenceProfile: RequestedInferenceProfile;
  /** original profile while editing a durable user message */
  editingInferenceProfile?: RequestedInferenceProfile | null;
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
    action: ChatAction | null,
    inferenceProfile: RequestedInferenceProfile,
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
  /** whether direct composer input is disabled while preserving controls like Stop */
  inputDisabled?: boolean;
  /** placeholder shown when direct composer input is disabled */
  disabledPlaceholder?: string | null;
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
    "skill_path" in action &&
    typeof action.skill_path === "string"
  ) {
    return { type: "skill", skill_path: action.skill_path };
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
  inferenceProfile: RequestedInferenceProfile | null;
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
  if (action.type === "skill" && typeof action.skill_path === "string") {
    return { type: "skill", skill_path: action.skill_path };
  }
  return null;
}

function storedReasoningEffort(value: unknown): ModelReasoningEffort | null {
  switch (value) {
    case "low":
    case "medium":
    case "high":
      return value;
    default:
      return null;
  }
}

function normalizeStoredInferenceProfile(
  value: unknown,
): RequestedInferenceProfile | null {
  if (
    typeof value !== "object" ||
    value === null ||
    !("model_target_label" in value) ||
    typeof value.model_target_label !== "string" ||
    value.model_target_label.length === 0 ||
    !("reasoning_effort" in value)
  ) {
    return null;
  }
  if (
    value.reasoning_effort !== null &&
    storedReasoningEffort(value.reasoning_effort) === null
  ) {
    return null;
  }
  return {
    model_target_label: value.model_target_label,
    reasoning_effort: storedReasoningEffort(value.reasoning_effort),
  };
}

function parseComposerDraft(raw: string): ComposerDraft {
  if (!raw) {
    return { message: "", action: null, inferenceProfile: null };
  }
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value === "object" && value !== null && "message" in value) {
      const record = value as Record<string, unknown>;
      return {
        message: typeof record.message === "string" ? record.message : "",
        action: normalizeStoredAction(record.action),
        inferenceProfile: normalizeStoredInferenceProfile(
          record.inference_profile,
        ),
      };
    }
  } catch {
    // Legacy drafts were stored as plain message strings.
  }
  return { message: raw, action: null, inferenceProfile: null };
}

function serializeComposerDraft(
  message: string,
  action: ChatAction | null,
  inferenceProfile: RequestedInferenceProfile,
): string {
  return JSON.stringify({
    message,
    action,
    inference_profile: inferenceProfile,
  });
}

function actionKey(action: ChatAction | null): string {
  return JSON.stringify(action);
}

function effortLevelsForTarget(
  options: AgentResponse["selectable_model_options"],
  targetLabel: string,
): ModelReasoningEffort[] {
  const reasoning = options.find((option) => option.label === targetLabel)
    ?.model_selection.normalized_capabilities.reasoning;
  if (!reasoning?.supported) {
    return [];
  }
  return reasoning.effort_levels?.length
    ? reasoning.effort_levels
    : ALL_REASONING_EFFORTS;
}

function normalizeProfileForOptions(
  profile: RequestedInferenceProfile | null,
  options: AgentResponse["selectable_model_options"],
  fallback: RequestedInferenceProfile,
): RequestedInferenceProfile {
  const fallbackOption =
    options.find((option) => option.label === fallback.model_target_label) ??
    options.at(0);
  const option =
    profile === null
      ? fallbackOption
      : (options.find(
          (candidate) => candidate.label === profile.model_target_label,
        ) ?? fallbackOption);
  const modelTargetLabel = option?.label ?? fallback.model_target_label;
  const effortLevels = effortLevelsForTarget(options, modelTargetLabel);
  const requestedEffort =
    profile?.model_target_label === modelTargetLabel
      ? profile.reasoning_effort
      : fallback.model_target_label === modelTargetLabel
        ? fallback.reasoning_effort
        : null;
  return {
    model_target_label: modelTargetLabel,
    reasoning_effort:
      requestedEffort !== null && effortLevels.includes(requestedEffort)
        ? requestedEffort
        : null,
  };
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
        id: `skill:${action.skill_path}`,
        keyword: "skill",
        label: "Skill",
        description: "",
        action,
        category: "turn",
        message: { policy: "optional", placeholder: null, max_length: null },
        attachments: { policy: "unsupported" },
        availability_hint: null,
      };
    case "create_git_worktree":
      return {
        id: `create_git_worktree:${action.source_project_path}:${action.starting_ref}`,
        keyword: "worktree",
        label: "Create worktree",
        description: "",
        action,
        category: "turn",
        message: { policy: "optional", placeholder: null, max_length: null },
        attachments: { policy: "unsupported" },
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
  selectableModelOptions,
  defaultInferenceProfile,
  editingInferenceProfile = null,
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
  inputDisabled = false,
  disabledPlaceholder = null,
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
  const normalizedDefaultProfile = useMemo(
    () =>
      normalizeProfileForOptions(
        defaultInferenceProfile,
        selectableModelOptions,
        defaultInferenceProfile,
      ),
    [defaultInferenceProfile, selectableModelOptions],
  );
  const normalizedDraftProfile = useMemo(
    () =>
      normalizeProfileForOptions(
        parsedDraft.inferenceProfile,
        selectableModelOptions,
        normalizedDefaultProfile,
      ),
    [
      normalizedDefaultProfile,
      parsedDraft.inferenceProfile,
      selectableModelOptions,
    ],
  );
  const [inputValue, setInputValue] = useState(
    initialInputValue ?? parsedDraft.message,
  );
  const [inferenceProfile, setInferenceProfile] = useState(
    normalizedDraftProfile,
  );
  const [profileDrawerOpened, setProfileDrawerOpened] = useState(false);
  const [sendErrorVisible, setSendErrorVisible] = useState(false);
  const [selectedAction, setSelectedAction] =
    useState<InputActionDefinition | null>(() =>
      resolveActionDefinition(parsedDraft.action, inputActions),
    );
  const modelSelectData = useMemo(
    () =>
      selectableModelOptions.map((option) => ({
        value: option.label,
        label: option.label,
      })),
    [selectableModelOptions],
  );
  const selectableEfforts = useMemo(
    () =>
      effortLevelsForTarget(
        selectableModelOptions,
        inferenceProfile.model_target_label,
      ),
    [inferenceProfile.model_target_label, selectableModelOptions],
  );
  const effortSelectData = useMemo(
    () => [
      { value: "default", label: t("composerProfile.defaultEffort") },
      ...selectableEfforts.map((effort) => ({
        value: effort,
        label: t(`composerProfile.effort.${effort}`),
      })),
    ],
    [selectableEfforts, t],
  );
  const selectedModelLabel =
    selectableModelOptions.find(
      (option) => option.label === inferenceProfile.model_target_label,
    )?.label ?? inferenceProfile.model_target_label;
  const selectedEffortLabel =
    inferenceProfile.reasoning_effort === null
      ? t("composerProfile.defaultEffort")
      : t(`composerProfile.effort.${inferenceProfile.reasoning_effort}`);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const previousEditingMessageIdRef = useRef<string | null>(null);
  const inputActionQuery = inputDisabled
    ? null
    : selectedAction
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
      setInferenceProfile(normalizedDefaultProfile);
      return;
    }
    setInputValue(parsedDraft.message);
    setSelectedAction(
      resolveActionDefinition(parsedDraft.action, inputActions),
    );
    setInferenceProfile(normalizedDraftProfile);
  }, [
    editingMessageId,
    initialInputValue,
    inputActions,
    normalizedDefaultProfile,
    normalizedDraftProfile,
    parsedDraft,
  ]);

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
    (
      message: string,
      action: ChatAction | null,
      profile: RequestedInferenceProfile,
    ): void => {
      if (editingMessageId !== null || !draftStorageKey) {
        return;
      }
      setDraftValue(serializeComposerDraft(message, action, profile));
    },
    [draftStorageKey, editingMessageId, setDraftValue],
  );

  const updateInputValue = useCallback(
    (nextValue: string): void => {
      setSendErrorVisible(false);
      setInputValue(nextValue);
      persistDraft(
        nextValue,
        selectedAction === null ? null : normalizeAction(selectedAction.action),
        inferenceProfile,
      );
    },
    [inferenceProfile, persistDraft, selectedAction],
  );

  useEffect(() => {
    if (editingMessageId !== previousEditingMessageIdRef.current) {
      previousEditingMessageIdRef.current = editingMessageId;
      if (editingMessageId !== null) {
        setSelectedAction(null);
        setInputValue(editingInitialValue ?? "");
        setInferenceProfile(
          normalizeProfileForOptions(
            editingInferenceProfile,
            selectableModelOptions,
            normalizedDefaultProfile,
          ),
        );
        textareaRef.current?.focus();
      }
    }
  }, [
    editingInferenceProfile,
    editingInitialValue,
    editingMessageId,
    normalizedDefaultProfile,
    selectableModelOptions,
  ]);

  const restorePersistedDraft = useCallback((): void => {
    setInputValue(parsedDraft.message);
    setSelectedAction(
      resolveActionDefinition(parsedDraft.action, inputActions),
    );
    setInferenceProfile(normalizedDraftProfile);
  }, [inputActions, normalizedDraftProfile, parsedDraft]);

  const handleCancelEdit = useCallback((): void => {
    restorePersistedDraft();
    previousEditingMessageIdRef.current = null;
    onCancelEdit?.();
  }, [onCancelEdit, restorePersistedDraft]);

  const clearInputAfterSend = useCallback((): void => {
    setSendErrorVisible(false);
    if (editingMessageId !== null) {
      restorePersistedDraft();
    } else {
      setSelectedAction(null);
      setInputValue("");
      setInferenceProfile(normalizedDefaultProfile);
      clearDraft();
    }
    clearFiles();
    onAfterSend();
  }, [
    clearDraft,
    clearFiles,
    editingMessageId,
    normalizedDefaultProfile,
    onAfterSend,
    restorePersistedDraft,
  ]);

  const handleSend = useCallback((): void => {
    const send = async (): Promise<void> => {
      const trimmed = inputValue.trim();
      const normalizedAction =
        selectedAction === null ? null : normalizeAction(selectedAction.action);
      if (inputDisabled || isUploading || editSendDisabled) {
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
              inferenceProfile,
            );
            if (sentWithoutAttachments) {
              clearInputAfterSend();
            } else {
              setSendErrorVisible(true);
            }
            return;
          }
          const sent = await onSendInput(
            trimmed,
            normalizedAction,
            inferenceProfile,
            uploaded,
          );
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

      const sent = await onSendInput(
        trimmed,
        normalizedAction,
        inferenceProfile,
      );
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
    inferenceProfile,
    isUploading,
    editSendDisabled,
    inputDisabled,
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
      persistDraft("", normalizedAction, inferenceProfile);
      textareaRef.current?.focus();
    },
    [inferenceProfile, persistDraft],
  );

  const updateInferenceProfile = useCallback(
    (nextProfile: RequestedInferenceProfile): void => {
      setInferenceProfile(nextProfile);
      persistDraft(
        inputValue,
        selectedAction === null ? null : normalizeAction(selectedAction.action),
        nextProfile,
      );
    },
    [inputValue, persistDraft, selectedAction],
  );

  const handleModelChange = useCallback(
    (modelTargetLabel: string | null): void => {
      if (modelTargetLabel === null) {
        return;
      }
      const nextEfforts = effortLevelsForTarget(
        selectableModelOptions,
        modelTargetLabel,
      );
      const currentEffort = inferenceProfile.reasoning_effort;
      updateInferenceProfile({
        model_target_label: modelTargetLabel,
        reasoning_effort:
          currentEffort !== null && nextEfforts.includes(currentEffort)
            ? currentEffort
            : null,
      });
    },
    [
      inferenceProfile.reasoning_effort,
      selectableModelOptions,
      updateInferenceProfile,
    ],
  );

  const handleEffortChange = useCallback(
    (value: string | null): void => {
      updateInferenceProfile({
        ...inferenceProfile,
        reasoning_effort:
          value === "default" ? null : storedReasoningEffort(value),
      });
    },
    [inferenceProfile, updateInferenceProfile],
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
          <Paper
            withBorder
            radius="md"
            p="xs"
            style={{
              maxHeight: `min(40dvh, ${rem(320)})`,
              overflowY: "auto",
              overflowX: "hidden",
              overscrollBehavior: "contain",
            }}
          >
            <Stack gap={rem(2)}>
              <Text size="xs" c="dimmed" px="xs">
                {t("slashCommands.title")}
              </Text>
              {visibleInputActions.map((ranked) => (
                <UnstyledButton
                  key={ranked.action.id}
                  onClick={() => handleSelectInputAction(ranked.action)}
                  px="xs"
                  py={rem(7)}
                  style={{ borderRadius: rem(8), width: "100%" }}
                >
                  <Stack gap={rem(3)} style={{ minWidth: 0 }}>
                    <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
                      <Text
                        size="sm"
                        fw={500}
                        style={{ flex: "0 0 auto", whiteSpace: "nowrap" }}
                      >
                        <HighlightedKeyword
                          keyword={ranked.action.keyword}
                          ranges={ranked.ranges}
                        />
                      </Text>
                      {(ranked.action.source_label ||
                        ranked.action.relative_hint) && (
                        <Text
                          size="xs"
                          c="dimmed"
                          truncate
                          style={{ flex: "1 1 auto", minWidth: 0 }}
                        >
                          {[
                            ranked.action.source_label,
                            ranked.action.relative_hint,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </Text>
                      )}
                    </Group>
                    <Text
                      size="xs"
                      c="dimmed"
                      lineClamp={2}
                      style={{ overflowWrap: "anywhere" }}
                    >
                      {ranked.action.description}
                    </Text>
                    {ranked.action.availability_hint?.message && (
                      <Text size="xs" c="orange" lineClamp={2}>
                        {ranked.action.availability_hint.message}
                      </Text>
                    )}
                  </Stack>
                </UnstyledButton>
              ))}
            </Stack>
          </Paper>
        )}
        <Paper
          withBorder
          radius="xl"
          px="xs"
          py={rem(6)}
          shadow="xs"
          style={{ position: "relative" }}
        >
          <Stack gap={rem(4)}>
            {pendingFiles.length > 0 && !editingMessageId && (
              <AttachmentPreviewBar
                pendingFiles={pendingFiles}
                onRemove={removeFile}
              />
            )}
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
            {selectedAction !== null && !editingMessageId && !inputDisabled && (
              <Group
                justify="space-between"
                gap="xs"
                wrap="nowrap"
                px="xs"
                py={rem(4)}
                style={{
                  borderRadius: rem(10),
                  background: "var(--mantine-color-blue-light)",
                }}
              >
                <Box style={{ minWidth: 0 }}>
                  <Text size="xs" fw={700} c="blue" truncate>
                    /{selectedAction.keyword}
                  </Text>
                  {selectedAction.availability_hint?.message && (
                    <Text size="xs" c="orange" lineClamp={1}>
                      {selectedAction.availability_hint.message}
                    </Text>
                  )}
                </Box>
                <ActionIcon
                  variant="subtle"
                  size={rem(32)}
                  c="dimmed"
                  onClick={() => {
                    setSelectedAction(null);
                    persistDraft(inputValue, null, inferenceProfile);
                    textareaRef.current?.focus();
                  }}
                  aria-label={t("cancelEdit")}
                >
                  <IconX size={14} />
                </ActionIcon>
              </Group>
            )}
            <Textarea
              ref={textareaRef}
              variant="unstyled"
              placeholder={
                inputDisabled
                  ? (disabledPlaceholder ?? t("inputDisabledPlaceholder"))
                  : (selectedAction?.message.placeholder ??
                    (isMobile
                      ? t("inputPlaceholder")
                      : t("inputPlaceholderDesktop")))
              }
              value={inputDisabled ? "" : inputValue}
              onChange={(event) => updateInputValue(event.currentTarget.value)}
              onKeyDown={handleKeyDown}
              onFocus={onFocus}
              disabled={inputDisabled}
              autosize
              minRows={1}
              maxRows={5}
              styles={{
                input: {
                  fontSize: rem(16),
                  lineHeight: 1.45,
                  paddingInline: rem(6),
                  paddingBlock: rem(4),
                },
              }}
            />
            <Group gap="xs" wrap="nowrap">
              <ActionIcon
                size={rem(40)}
                variant="subtle"
                onClick={() => fileInputRef.current?.click()}
                disabled={
                  inputDisabled ||
                  isUploading ||
                  Boolean(editingMessageId) ||
                  selectedAction?.attachments.policy === "unsupported"
                }
                aria-label={t("attachment.attach")}
              >
                <IconPaperclip size={18} />
              </ActionIcon>
              {isMobile ? (
                <>
                  <Button
                    variant="light"
                    size="compact-sm"
                    leftSection={<IconAdjustmentsHorizontal size={16} />}
                    rightSection={<IconChevronDown size={14} />}
                    disabled={
                      inputDisabled || selectableModelOptions.length === 0
                    }
                    onClick={() => setProfileDrawerOpened(true)}
                    aria-label={t("composerProfile.model")}
                    style={{
                      minWidth: 0,
                      minHeight: rem(40),
                      flex: "1 1 auto",
                    }}
                  >
                    <Text size="sm" truncate>
                      {selectableEfforts.length > 0
                        ? `${selectedModelLabel} · ${selectedEffortLabel}`
                        : selectedModelLabel}
                    </Text>
                  </Button>
                  <Drawer
                    opened={profileDrawerOpened}
                    onClose={() => setProfileDrawerOpened(false)}
                    title={t("composerProfile.model")}
                    position="bottom"
                    size="auto"
                    keepMounted
                    styles={{
                      content: {
                        borderTopLeftRadius: rem(12),
                        borderTopRightRadius: rem(12),
                      },
                      body: {
                        paddingBottom:
                          "max(var(--mantine-spacing-md), env(safe-area-inset-bottom))",
                      },
                    }}
                  >
                    <Stack gap="md">
                      <Select
                        label={t("composerProfile.model")}
                        data={modelSelectData}
                        value={inferenceProfile.model_target_label}
                        onChange={handleModelChange}
                        allowDeselect={false}
                        styles={{ input: { fontSize: rem(16) } }}
                      />
                      {selectableEfforts.length > 0 && (
                        <Select
                          label={t("composerProfile.effortLabel")}
                          data={effortSelectData}
                          value={inferenceProfile.reasoning_effort ?? "default"}
                          onChange={handleEffortChange}
                          allowDeselect={false}
                          styles={{ input: { fontSize: rem(16) } }}
                        />
                      )}
                    </Stack>
                  </Drawer>
                </>
              ) : (
                <>
                  <Select
                    aria-label={t("composerProfile.model")}
                    data={modelSelectData}
                    value={inferenceProfile.model_target_label}
                    onChange={handleModelChange}
                    allowDeselect={false}
                    disabled={inputDisabled || modelSelectData.length === 0}
                    w={rem(176)}
                    styles={{ input: { minHeight: rem(40) } }}
                  />
                  {selectableEfforts.length > 0 && (
                    <Select
                      aria-label={t("composerProfile.effortLabel")}
                      data={effortSelectData}
                      value={inferenceProfile.reasoning_effort ?? "default"}
                      onChange={handleEffortChange}
                      allowDeselect={false}
                      disabled={inputDisabled}
                      w={rem(136)}
                      styles={{ input: { minHeight: rem(40) } }}
                    />
                  )}
                </>
              )}
              <Box style={{ flex: "1 1 auto" }} />
              {isStopAvailable &&
              (inputDisabled ||
                (!inputValue.trim() && selectedAction === null)) ? (
                <ActionIcon
                  size={rem(40)}
                  variant="filled"
                  color="red"
                  onClick={onStopRequest}
                  onMouseDown={(event) => event.preventDefault()}
                  loading={isStopPending}
                  aria-label={t("stopRun")}
                >
                  <IconPlayerStop size={18} />
                </ActionIcon>
              ) : (
                <ActionIcon
                  size={rem(40)}
                  variant="filled"
                  onClick={handleSend}
                  onMouseDown={(event) => event.preventDefault()}
                  disabled={
                    inputDisabled ||
                    editSendDisabled ||
                    (!inputValue.trim() &&
                      selectedAction?.message.policy === "required")
                  }
                  loading={isUploading}
                  aria-label={t("composerProfile.send")}
                >
                  <IconSend size={18} />
                </ActionIcon>
              )}
            </Group>
          </Stack>
        </Paper>
      </Stack>
    </>
  );
});
