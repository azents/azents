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
  Popover,
  rem,
  Stack,
  Text,
  Textarea,
  UnstyledButton,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import {
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconPaperclip,
  IconPlayerStop,
  IconSend,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  normalizeReasoningEffort,
  reasoningEffortLevels,
} from "@/shared/lib/reasoning-effort";
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

function storedReasoningEffort(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function knownReasoningEffort(
  value: string | null,
): ModelReasoningEffort | null {
  switch (value) {
    case "none":
    case "minimal":
    case "low":
    case "medium":
    case "high":
    case "xhigh":
    case "max":
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
  const capabilities = options.find((option) => option.label === targetLabel)
    ?.model_selection.normalized_capabilities;
  return reasoningEffortLevels(capabilities);
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
  const requestedEffort =
    profile?.model_target_label === modelTargetLabel
      ? profile.reasoning_effort
      : fallback.model_target_label === modelTargetLabel
        ? fallback.reasoning_effort
        : null;
  return {
    model_target_label: modelTargetLabel,
    reasoning_effort: requestedEffort,
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
  const [profilePickerOpened, setProfilePickerOpened] = useState(false);
  const [desktopProfileSection, setDesktopProfileSection] = useState<
    "model" | "effort" | null
  >(null);
  const [sendErrorVisible, setSendErrorVisible] = useState(false);
  const [selectedAction, setSelectedAction] =
    useState<InputActionDefinition | null>(() =>
      resolveActionDefinition(parsedDraft.action, inputActions),
    );
  const selectableEfforts = useMemo(
    () =>
      effortLevelsForTarget(
        selectableModelOptions,
        inferenceProfile.model_target_label,
      ),
    [inferenceProfile.model_target_label, selectableModelOptions],
  );
  const selectedModelLabel =
    selectableModelOptions.find(
      (option) => option.label === inferenceProfile.model_target_label,
    )?.label ?? inferenceProfile.model_target_label;
  const selectedEffortLabel = inferenceProfile.reasoning_effort ?? "";
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
  const todoPreviewVisible =
    todo !== null &&
    editingMessageId === null &&
    ((Boolean(goal?.objective) && goal?.status !== "complete") ||
      todo.items.some((item) => item.status !== "completed"));

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
      updateInferenceProfile({
        model_target_label: modelTargetLabel,
        reasoning_effort: normalizeReasoningEffort(
          knownReasoningEffort(inferenceProfile.reasoning_effort),
          nextEfforts,
        ),
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
      const effort = selectableEfforts.find((candidate) => candidate === value);
      if (!effort) {
        return;
      }
      updateInferenceProfile({
        ...inferenceProfile,
        reasoning_effort: effort,
      });
    },
    [inferenceProfile, selectableEfforts, updateInferenceProfile],
  );

  const profileTrigger = (
    <Button
      variant="light"
      size="compact-sm"
      radius={rem(12)}
      disabled={inputDisabled || selectableModelOptions.length === 0}
      onClick={() => {
        setProfilePickerOpened(!profilePickerOpened);
        if (profilePickerOpened) {
          setDesktopProfileSection(null);
        }
      }}
      rightSection={<IconChevronDown aria-hidden="true" size={14} />}
      aria-label={t("composerProfile.model")}
      style={{
        minWidth: rem(128),
        maxWidth: rem(224),
        minHeight: rem(36),
      }}
    >
      <Text size="sm" truncate style={{ maxWidth: "20ch", minWidth: 0 }}>
        {selectableEfforts.length > 0
          ? `${selectedModelLabel} · ${selectedEffortLabel}`
          : selectedModelLabel}
      </Text>
    </Button>
  );
  const modelOptionRows = selectableModelOptions.map((option, index) => {
    const selected = option.label === inferenceProfile.model_target_label;
    return (
      <UnstyledButton
        key={option.label}
        onClick={() => handleModelChange(option.label)}
        aria-pressed={selected}
        style={{
          background: selected
            ? "var(--mantine-color-default-hover)"
            : "var(--mantine-color-body)",
          borderTop:
            index === 0
              ? "none"
              : `${rem(1)} solid var(--mantine-color-default-border)`,
          display: "block",
          padding: `${rem(9)} ${rem(12)}`,
          textAlign: "left",
          width: "100%",
        }}
      >
        <Group gap="sm" justify="space-between" wrap="nowrap">
          <Stack gap={rem(1)} style={{ minWidth: 0 }}>
            <Text size="sm" fw={600} lh={rem(18)} truncate>
              {option.label}
            </Text>
            <Text size="xs" c="dimmed" lh={rem(16)} truncate>
              {option.model_selection.model_identifier}
            </Text>
          </Stack>
          {selected && (
            <IconCheck
              aria-hidden="true"
              size={16}
              color="var(--mantine-color-blue-6)"
              style={{ flexShrink: 0 }}
            />
          )}
        </Group>
      </UnstyledButton>
    );
  });
  const effortOptionRows = selectableEfforts.map((effort, index) => {
    const selected = effort === inferenceProfile.reasoning_effort;
    return (
      <UnstyledButton
        key={effort}
        onClick={() => handleEffortChange(effort)}
        aria-pressed={selected}
        style={{
          background: selected
            ? "var(--mantine-color-default-hover)"
            : "var(--mantine-color-body)",
          borderTop:
            index === 0
              ? "none"
              : `${rem(1)} solid var(--mantine-color-default-border)`,
          display: "block",
          padding: `${rem(12)}`,
          textAlign: "left",
          width: "100%",
        }}
      >
        <Group gap="sm" justify="space-between" wrap="nowrap">
          <Text size="sm" fw={600} lh={rem(18)}>
            {effort}
          </Text>
          {selected && (
            <IconCheck
              aria-hidden="true"
              size={16}
              color="var(--mantine-color-blue-6)"
              style={{ flexShrink: 0 }}
            />
          )}
        </Group>
      </UnstyledButton>
    );
  });
  const mobileProfilePickerContent = (
    <Stack gap="md">
      <Stack
        gap={0}
        style={{
          border: `${rem(1)} solid var(--mantine-color-default-border)`,
          borderRadius: rem(12),
          overflow: "hidden",
        }}
      >
        {modelOptionRows}
      </Stack>
      {selectableEfforts.length > 0 && (
        <Stack gap={rem(6)}>
          <Text size="sm" fw={600}>
            {t("composerProfile.effortLabel")}
          </Text>
          <Stack
            gap={0}
            style={{
              border: `${rem(1)} solid var(--mantine-color-default-border)`,
              borderRadius: rem(12),
              overflow: "hidden",
            }}
          >
            {effortOptionRows}
          </Stack>
        </Stack>
      )}
    </Stack>
  );
  const desktopProfileMenu = (
    <Group gap={rem(4)} align="flex-end" wrap="nowrap">
      <Paper withBorder radius={rem(12)} shadow="md" p={rem(6)} w={rem(260)}>
        <Stack gap={rem(2)}>
          <UnstyledButton
            onMouseEnter={() => setDesktopProfileSection("model")}
            onFocus={() => setDesktopProfileSection("model")}
            onClick={() => setDesktopProfileSection("model")}
            aria-expanded={desktopProfileSection === "model"}
            style={{
              background:
                desktopProfileSection === "model"
                  ? "var(--mantine-color-default-hover)"
                  : "transparent",
              borderRadius: rem(8),
              padding: `${rem(8)} ${rem(10)}`,
              width: "100%",
            }}
          >
            <Group justify="space-between" gap="md" wrap="nowrap">
              <Text size="sm" fw={500}>
                {t("composerProfile.model")}
              </Text>
              <Group gap={rem(6)} wrap="nowrap" style={{ minWidth: 0 }}>
                <Text size="sm" c="dimmed" truncate>
                  {selectedModelLabel}
                </Text>
                <IconChevronRight
                  aria-hidden="true"
                  size={16}
                  color="var(--mantine-color-dimmed)"
                  style={{ flexShrink: 0 }}
                />
              </Group>
            </Group>
          </UnstyledButton>
          {selectableEfforts.length > 0 && (
            <UnstyledButton
              onMouseEnter={() => setDesktopProfileSection("effort")}
              onFocus={() => setDesktopProfileSection("effort")}
              onClick={() => setDesktopProfileSection("effort")}
              aria-expanded={desktopProfileSection === "effort"}
              style={{
                background:
                  desktopProfileSection === "effort"
                    ? "var(--mantine-color-default-hover)"
                    : "transparent",
                borderRadius: rem(8),
                padding: `${rem(8)} ${rem(10)}`,
                width: "100%",
              }}
            >
              <Group justify="space-between" gap="md" wrap="nowrap">
                <Text size="sm" fw={500}>
                  {t("composerProfile.effortLabel")}
                </Text>
                <Group gap={rem(6)} wrap="nowrap">
                  <Text size="sm" c="dimmed">
                    {selectedEffortLabel}
                  </Text>
                  <IconChevronRight
                    aria-hidden="true"
                    size={16}
                    color="var(--mantine-color-dimmed)"
                  />
                </Group>
              </Group>
            </UnstyledButton>
          )}
        </Stack>
      </Paper>
      {desktopProfileSection === "model" && (
        <Paper
          withBorder
          radius={rem(12)}
          shadow="md"
          w={rem(280)}
          style={{ maxHeight: rem(280), overflowY: "auto" }}
        >
          <Stack gap={0}>{modelOptionRows}</Stack>
        </Paper>
      )}
      {desktopProfileSection === "effort" && selectableEfforts.length > 0 && (
        <Paper withBorder radius={rem(12)} shadow="md" p={rem(6)} w={rem(220)}>
          <Text size="xs" c="dimmed" fw={600} px={rem(8)} py={rem(4)}>
            {t("composerProfile.effortLabel")}
          </Text>
          <Stack gap={rem(2)}>
            {selectableEfforts.map((effort) => {
              const selected = effort === inferenceProfile.reasoning_effort;
              return (
                <UnstyledButton
                  key={effort}
                  onClick={() => handleEffortChange(effort)}
                  aria-pressed={selected}
                  style={{
                    background: selected
                      ? "var(--mantine-color-default-hover)"
                      : "transparent",
                    borderRadius: rem(8),
                    padding: `${rem(8)} ${rem(10)}`,
                    width: "100%",
                  }}
                >
                  <Group justify="space-between" gap="sm" wrap="nowrap">
                    <Text size="sm">{effort}</Text>
                    {selected && <IconCheck aria-hidden="true" size={16} />}
                  </Group>
                </UnstyledButton>
              );
            })}
          </Stack>
        </Paper>
      )}
    </Group>
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
            mb={todoPreviewVisible ? rem(22) : 0}
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
          radius={rem(12)}
          px="xs"
          py={rem(6)}
          shadow="xs"
          style={{
            position: "relative",
            border: `${rem(1)} solid var(--mantine-color-default-border)`,
            background: "var(--mantine-color-body)",
          }}
        >
          <Stack gap={rem(4)}>
            {pendingFiles.length > 0 && !editingMessageId && (
              <AttachmentPreviewBar
                pendingFiles={pendingFiles}
                onRemove={removeFile}
              />
            )}
            {todoPreviewVisible && (
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
              <Stack gap={rem(2)} align="flex-start">
                <Group
                  gap={rem(4)}
                  wrap="nowrap"
                  px={rem(8)}
                  py={rem(3)}
                  style={{
                    borderRadius: rem(999),
                    background: "var(--mantine-color-blue-light)",
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
                    onClick={() => {
                      setSelectedAction(null);
                      persistDraft(inputValue, null, inferenceProfile);
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
                size={rem(36)}
                radius={rem(12)}
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
                <IconPaperclip size={17} />
              </ActionIcon>
              {isMobile ? (
                <>
                  {profileTrigger}
                  <Drawer
                    opened={profilePickerOpened}
                    onClose={() => setProfilePickerOpened(false)}
                    title={
                      <Group
                        justify="space-between"
                        gap="md"
                        wrap="nowrap"
                        w="100%"
                      >
                        <Text component="span" inherit>
                          {t("composerProfile.model")}
                        </Text>
                        <Button
                          variant="subtle"
                          color="blue"
                          size="compact-sm"
                          px="xs"
                          onClick={() => setProfilePickerOpened(false)}
                        >
                          {t("composerProfile.done")}
                        </Button>
                      </Group>
                    }
                    position="bottom"
                    size={`min(80dvh, ${rem(720)})`}
                    withCloseButton={false}
                    keepMounted
                    styles={{
                      title: { flex: 1 },
                      content: {
                        borderTopLeftRadius: rem(12),
                        borderTopRightRadius: rem(12),
                      },
                      body: {
                        overflowY: "auto",
                        paddingBottom:
                          "max(var(--mantine-spacing-md), env(safe-area-inset-bottom))",
                      },
                    }}
                  >
                    {mobileProfilePickerContent}
                  </Drawer>
                </>
              ) : (
                <Popover
                  opened={profilePickerOpened}
                  onChange={(opened) => {
                    setProfilePickerOpened(opened);
                    if (!opened) {
                      setDesktopProfileSection(null);
                    }
                  }}
                  position="top-start"
                  width="auto"
                  shadow="none"
                  withinPortal
                >
                  <Popover.Target>{profileTrigger}</Popover.Target>
                  <Popover.Dropdown
                    p={0}
                    style={{
                      background: "transparent",
                      border: 0,
                      boxShadow: "none",
                      overflow: "visible",
                    }}
                  >
                    {desktopProfileMenu}
                  </Popover.Dropdown>
                </Popover>
              )}
              <Box style={{ flex: "1 1 auto" }} />
              {isStopAvailable &&
              (inputDisabled ||
                (!inputValue.trim() && selectedAction === null)) ? (
                <ActionIcon
                  size={rem(36)}
                  radius={rem(12)}
                  variant="filled"
                  color="red"
                  onClick={onStopRequest}
                  onMouseDown={(event) => event.preventDefault()}
                  loading={isStopPending}
                  aria-label={t("stopRun")}
                >
                  <IconPlayerStop size={17} />
                </ActionIcon>
              ) : (
                <ActionIcon
                  size={rem(36)}
                  radius={rem(12)}
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
                  <IconSend size={17} />
                </ActionIcon>
              )}
            </Group>
          </Stack>
        </Paper>
      </Stack>
    </>
  );
});
