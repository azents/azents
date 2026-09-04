"use client";

import { useLocalStorage } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  normalizeReasoningEffort,
  reasoningEffortLevels,
} from "@/shared/lib/reasoning-effort";
import { isRecord, isString } from "@/shared/lib/unknown-value";
import { resolveAppliedInferenceProfile } from "../inferenceProfileBaseline";
import type {
  ChatAction,
  ChatLiveRunState,
  GoalStateSnapshot,
  InputActionDefinition,
  TodoStateSnapshot,
  TokenUsageSummary,
} from "../types";
import type {
  PendingFile,
  UploadedFile,
} from "@/shared/file-upload/useFileUpload";
import type {
  AgentResponse,
  ModelReasoningEffort,
  RequestedInferenceProfile,
} from "@azents/public-client";

const DRAFT_STORAGE_KEY_PREFIX = "azents.chat.inputDraft";

function getScopedStorageKey(
  prefix: string,
  agentId: string | null,
  sessionId: string | null,
): string | null {
  if (!agentId) {
    return null;
  }
  return `${prefix}.${agentId}.${sessionId ?? "new"}`;
}

export interface ChatInputProps {
  /** current agent ID */
  agentId: string | null;
  /** current session ID */
  sessionId: string | null;
  /** Whether the mobile composer layout is active */
  isMobile: boolean;
  /** Agent-owned selectable model targets */
  selectableModelOptions: AgentResponse["selectable_model_options"];
  /** current Agent default used when the Session has no applied profile */
  defaultInferenceProfile: RequestedInferenceProfile;
  /** durable Session profile used by temporary model-change visual reviews */
  appliedInferenceProfile?: RequestedInferenceProfile | null;
  /** original profile while editing a durable user message */
  editingInferenceProfile?: RequestedInferenceProfile | null;
  /** whether the model and reasoning-effort picker is available */
  inferenceProfileSelectionEnabled?: boolean;
  /** whether context-window usage is shown below the model picker */
  contextUsageEnabled?: boolean;
  /** latest context-window usage snapshot */
  contextUsage?: TokenUsageSummary | null;
  /** active run used to resolve transient inference provenance */
  contextUsageActiveRun?: ChatLiveRunState | null;
  /** applies a pending profile without creating a message or Run */
  onApplyInferenceProfile?: (
    profile: RequestedInferenceProfile,
  ) => Promise<boolean>;
  /** Whether any attachment is currently uploading */
  isUploading: boolean;
  /** pending file list */
  pendingFiles: PendingFile[];
  /** Goal snapshot displayed above the composer */
  goal: GoalStateSnapshot | null;
  /** Todo snapshot displayed above the composer */
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
  /** Reset completed attachment states after sending */
  resetDoneFiles: () => void;
  /** file add callback */
  addFiles: (files: FileList) => void;
  /** file remove callback */
  removeFile: (id: string) => void;
  /** scroll callback after send */
  onAfterSend: () => void;
  /** Adjust the chat scroll position when the composer receives focus */
  onFocus?: () => void;
  /** whether commands are blocked during Run */
  wasCommandBlocked: boolean;
  /** Whether the current Session state permits a Stop request */
  isStopAvailable: boolean;
  /** whether stop request is being sent */
  isStopPending: boolean;
  /** run stop request callback */
  onStopRequest: () => void;
  /** server-managed input action list */
  inputActions: InputActionDefinition[];
  /** Initial input value for Storybook and other controlled previews */
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
  if (type === "cleanup_orphan_git_worktrees") {
    return { type: "cleanup_orphan_git_worktrees" };
  }
  return null;
}

function getInputActionQuery(inputValue: string): string | null {
  if (!inputValue.startsWith("/")) {
    return null;
  }

  const commandSegment = inputValue.slice(1).match(/^\S*/)?.[0] ?? "";
  return commandSegment.toLowerCase();
}

function getInputActionMessage(inputValue: string): string {
  return inputValue.slice(1).replace(/^\S*\s*/, "");
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

type DesktopProfileSection = "model" | "effort";

interface DesktopProfileFocusTarget {
  section: DesktopProfileSection;
  optionIndex: number | null;
}

function normalizeStoredAction(value: unknown): ChatAction | null {
  if (!isRecord(value)) {
    return null;
  }
  if (value.type === "command" && isString(value.name)) {
    return { type: "command", name: value.name };
  }
  if (value.type === "goal") {
    return { type: "goal" };
  }
  if (value.type === "skill" && isString(value.skill_path)) {
    return { type: "skill", skill_path: value.skill_path };
  }
  if (value.type === "cleanup_orphan_git_worktrees") {
    return { type: "cleanup_orphan_git_worktrees" };
  }
  return null;
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

function parseComposerDraft(raw: string): ComposerDraft {
  if (!raw) {
    return { message: "", action: null };
  }
  try {
    const value: unknown = JSON.parse(raw);
    if (isRecord(value) && "message" in value) {
      return {
        message: isString(value.message) ? value.message : "",
        action: normalizeStoredAction(value.action),
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
  return JSON.stringify({
    message,
    action,
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

function normalizeDefaultProfileForOptions(
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
    case "cleanup_orphan_git_worktrees":
      return {
        id: "cleanup_orphan_git_worktrees",
        keyword: "cleanup-worktrees",
        label: "Clean up worktrees",
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

function useChatInputContainerImplementation({
  agentId,
  sessionId,
  isMobile,
  selectableModelOptions,
  defaultInferenceProfile,
  appliedInferenceProfile = null,
  editingInferenceProfile = null,
  inferenceProfileSelectionEnabled = true,
  contextUsageEnabled = false,
  contextUsage = null,
  contextUsageActiveRun = null,
  onApplyInferenceProfile,
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
}: ChatInputProps) {
  const t = useTranslations("chat");
  const draftStorageKey = useMemo(
    () => getScopedStorageKey(DRAFT_STORAGE_KEY_PREFIX, agentId, sessionId),
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
      normalizeDefaultProfileForOptions(
        defaultInferenceProfile,
        selectableModelOptions,
        defaultInferenceProfile,
      ),
    [defaultInferenceProfile, selectableModelOptions],
  );
  const effectiveAppliedInferenceProfile = resolveAppliedInferenceProfile(
    appliedInferenceProfile,
    normalizedDefaultProfile,
  );
  const profileIdentity = `${agentId ?? ""}:${sessionId ?? "new"}`;
  const [inputValue, setInputValue] = useState(
    initialInputValue ?? parsedDraft.message,
  );
  const [inferenceProfile, setInferenceProfile] = useState(
    effectiveAppliedInferenceProfile,
  );
  const profileDirtyRef = useRef(false);
  const profileIdentityRef = useRef(profileIdentity);
  const [profilePickerOpened, setProfilePickerOpened] = useState(false);
  const [scrollToContextUsageOnOpen, setScrollToContextUsageOnOpen] =
    useState(false);
  const contextUsageDetailsRef = useRef<HTMLDivElement>(null);
  const [desktopProfileSection, setDesktopProfileSection] = useState<
    "model" | "effort" | null
  >(null);
  const [desktopProfileFocusTarget, setDesktopProfileFocusTarget] =
    useState<DesktopProfileFocusTarget | null>(null);
  const [sendErrorVisible, setSendErrorVisible] = useState(false);
  const [selectedAction, setSelectedAction] =
    useState<InputActionDefinition | null>(() =>
      resolveActionDefinition(parsedDraft.action, inputActions),
    );
  const [inputActionSuggestionsDismissed, setInputActionSuggestionsDismissed] =
    useState(false);
  const [inputActionSuggestionsFocused, setInputActionSuggestionsFocused] =
    useState(false);
  const [activeInputActionIndex, setActiveInputActionIndex] = useState(0);
  const inputActionListboxId = useId();
  const inputActionOptionRefs = useRef(new Map<number, HTMLButtonElement>());
  const desktopProfileDialogId = useId();
  const desktopProfileModelPanelId = useId();
  const desktopProfileEffortPanelId = useId();
  const profileTriggerRef = useRef<HTMLButtonElement>(null);
  const desktopProfileSectionRefs = useRef(
    new Map<DesktopProfileSection, HTMLButtonElement>(),
  );
  const desktopModelOptionRefs = useRef(new Map<number, HTMLButtonElement>());
  const desktopEffortOptionRefs = useRef(new Map<number, HTMLButtonElement>());
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
  const hasPendingInferenceProfileChange =
    effectiveAppliedInferenceProfile.model_target_label !==
      inferenceProfile.model_target_label ||
    effectiveAppliedInferenceProfile.reasoning_effort !==
      inferenceProfile.reasoning_effort;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const previousEditingMessageIdRef = useRef<string | null>(null);
  const inputActionQuery = inputDisabled
    ? null
    : selectedAction
      ? null
      : inputActionSuggestionsDismissed || !inputActionSuggestionsFocused
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
  const activeInputAction = visibleInputActions[activeInputActionIndex] ?? null;
  const activeInputActionOptionId = `${inputActionListboxId}-option-${activeInputActionIndex}`;

  useEffect(() => {
    setActiveInputActionIndex(0);
  }, [visibleInputActions]);

  useEffect(() => {
    inputActionOptionRefs.current
      .get(activeInputActionIndex)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeInputActionIndex, visibleInputActions]);

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
    const identityChanged = profileIdentityRef.current !== profileIdentity;
    const matchesEffectiveBaseline =
      effectiveAppliedInferenceProfile.model_target_label ===
        inferenceProfile.model_target_label &&
      effectiveAppliedInferenceProfile.reasoning_effort ===
        inferenceProfile.reasoning_effort;
    if (identityChanged) {
      profileIdentityRef.current = profileIdentity;
      profileDirtyRef.current = false;
      setInferenceProfile(effectiveAppliedInferenceProfile);
      return;
    }
    if (!profileDirtyRef.current || matchesEffectiveBaseline) {
      profileDirtyRef.current = false;
      setInferenceProfile(effectiveAppliedInferenceProfile);
    }
  }, [effectiveAppliedInferenceProfile, inferenceProfile, profileIdentity]);

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
      setDraftValue(serializeComposerDraft(message, action));
    },
    [draftStorageKey, editingMessageId, setDraftValue],
  );

  const updateInputValue = useCallback(
    (nextValue: string): void => {
      setSendErrorVisible(false);
      setInputActionSuggestionsDismissed(false);
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
        setInferenceProfile(
          normalizeDefaultProfileForOptions(
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
    setInferenceProfile(effectiveAppliedInferenceProfile);
    profileDirtyRef.current = false;
  }, [effectiveAppliedInferenceProfile, inputActions, parsedDraft]);

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
      clearDraft();
    }
    clearFiles();
    onAfterSend();
  }, [
    clearDraft,
    clearFiles,
    editingMessageId,
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
      if (
        hasPendingInferenceProfileChange &&
        !trimmed &&
        !hasAttachedFiles &&
        selectedAction === null &&
        onApplyInferenceProfile != null
      ) {
        const applied = await onApplyInferenceProfile(inferenceProfile);
        if (!applied) {
          setSendErrorVisible(true);
        }
        return;
      }
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

      // Upload attachments for the selected Agent before sending the message.
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
    onApplyInferenceProfile,
    hasPendingInferenceProfileChange,
    clearInputAfterSend,
    clearFiles,
    resetDoneFiles,
  ]);

  const handleSelectInputAction = useCallback(
    (definition: InputActionDefinition): void => {
      const normalizedAction = normalizeAction(definition.action);
      if (normalizedAction === null) {
        return;
      }
      setSelectedAction(definition);
      setInputActionSuggestionsDismissed(false);
      setActiveInputActionIndex(0);
      const message = getInputActionMessage(inputValue);
      setInputValue(message);
      persistDraft(message, normalizedAction);
      textareaRef.current?.focus();
    },
    [inputValue, persistDraft],
  );

  const handleInputFocus = useCallback((): void => {
    setInputActionSuggestionsFocused(true);
    onFocus?.();
  }, [onFocus]);

  const handleInputBlur = useCallback((): void => {
    setInputActionSuggestionsFocused(false);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (
        !e.nativeEvent.isComposing &&
        visibleInputActions.length > 0 &&
        e.key === "Escape"
      ) {
        e.preventDefault();
        setInputActionSuggestionsDismissed(true);
        return;
      }
      if (!e.nativeEvent.isComposing && visibleInputActions.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setActiveInputActionIndex((index) =>
            Math.min(index + 1, visibleInputActions.length - 1),
          );
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setActiveInputActionIndex((index) => Math.max(index - 1, 0));
          return;
        }
        if (e.key === "Enter" && activeInputAction !== null) {
          e.preventDefault();
          handleSelectInputAction(activeInputAction.action);
          return;
        }
      }
      // On mobile, Enter inserts a line break; messages are sent with the button.
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
    [
      activeInputAction,
      handleSelectInputAction,
      handleSend,
      isMobile,
      visibleInputActions,
    ],
  );

  /** Handle files selected through the hidden input. */
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        addFiles(e.target.files);
      }
      // Clear the input so selecting the same file again triggers a change.
      e.target.value = "";
    },
    [addFiles],
  );

  const updateInferenceProfile = useCallback(
    (nextProfile: RequestedInferenceProfile): void => {
      profileDirtyRef.current = true;
      setInferenceProfile(nextProfile);
    },
    [],
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

  const handleOpenContextUsage = useCallback((): void => {
    setScrollToContextUsageOnOpen(true);
    setProfilePickerOpened(true);
    setDesktopProfileSection(null);
  }, []);

  const handleProfilePickerEnterTransitionEnd = useCallback((): void => {
    if (!scrollToContextUsageOnOpen) {
      return;
    }
    setScrollToContextUsageOnOpen(false);
    contextUsageDetailsRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }, [scrollToContextUsageOnOpen]);

  useEffect(() => {
    if (isMobile || !profilePickerOpened || !scrollToContextUsageOnOpen) {
      return;
    }
    const frame = requestAnimationFrame(() => {
      contextUsageDetailsRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      setScrollToContextUsageOnOpen(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [isMobile, profilePickerOpened, scrollToContextUsageOnOpen]);

  const desktopProfileSections = useMemo<DesktopProfileSection[]>(
    () => (selectableEfforts.length > 0 ? ["model", "effort"] : ["model"]),
    [selectableEfforts.length],
  );

  const focusDesktopProfileSection = useCallback(
    (section: DesktopProfileSection): void => {
      setDesktopProfileFocusTarget({ section, optionIndex: null });
    },
    [],
  );

  const closeDesktopProfilePicker = useCallback((): void => {
    setProfilePickerOpened(false);
    setDesktopProfileSection(null);
    setDesktopProfileFocusTarget(null);
    profileTriggerRef.current?.focus();
  }, []);

  const focusDesktopProfileOption = useCallback(
    (section: DesktopProfileSection, index: number): void => {
      setDesktopProfileFocusTarget({ section, optionIndex: index });
    },
    [],
  );

  useEffect(() => {
    if (isMobile || desktopProfileFocusTarget === null) {
      return;
    }
    let frame = 0;
    let attempts = 0;
    const focusTarget = (): void => {
      const target =
        desktopProfileFocusTarget.optionIndex === null
          ? desktopProfileSectionRefs.current.get(
              desktopProfileFocusTarget.section,
            )
          : desktopProfileFocusTarget.section === "model"
            ? desktopModelOptionRefs.current.get(
                desktopProfileFocusTarget.optionIndex,
              )
            : desktopEffortOptionRefs.current.get(
                desktopProfileFocusTarget.optionIndex,
              );
      if (target) {
        target.focus();
        setDesktopProfileFocusTarget(null);
        return;
      }
      attempts += 1;
      if (attempts < 4) {
        frame = requestAnimationFrame(focusTarget);
      } else {
        setDesktopProfileFocusTarget(null);
      }
    };
    frame = requestAnimationFrame(focusTarget);
    return () => cancelAnimationFrame(frame);
  }, [desktopProfileFocusTarget, isMobile]);

  const openDesktopProfileSection = useCallback(
    (section: DesktopProfileSection): void => {
      setDesktopProfileSection(section);
      const selectedIndex =
        section === "model"
          ? Math.max(
              0,
              selectableModelOptions.findIndex(
                (option) =>
                  option.label === inferenceProfile.model_target_label,
              ),
            )
          : Math.max(
              0,
              selectableEfforts.findIndex(
                (effort) => effort === inferenceProfile.reasoning_effort,
              ),
            );
      focusDesktopProfileOption(section, selectedIndex);
    },
    [
      focusDesktopProfileOption,
      inferenceProfile.model_target_label,
      inferenceProfile.reasoning_effort,
      selectableEfforts,
      selectableModelOptions,
    ],
  );

  const handleDesktopProfileSectionKeyDown = useCallback(
    (
      section: DesktopProfileSection,
      event: React.KeyboardEvent<HTMLButtonElement>,
    ): void => {
      const index = desktopProfileSections.indexOf(section);
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const direction = event.key === "ArrowDown" ? 1 : -1;
        const nextIndex =
          (index + direction + desktopProfileSections.length) %
          desktopProfileSections.length;
        const nextSection = desktopProfileSections.at(nextIndex);
        if (nextSection) {
          focusDesktopProfileSection(nextSection);
        }
        return;
      }
      if (
        event.key === "ArrowRight" ||
        event.key === "Enter" ||
        event.key === " "
      ) {
        event.preventDefault();
        openDesktopProfileSection(section);
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "Escape") {
        event.preventDefault();
        closeDesktopProfilePicker();
      }
    },
    [
      closeDesktopProfilePicker,
      desktopProfileSections,
      focusDesktopProfileSection,
      openDesktopProfileSection,
    ],
  );

  const handleDesktopProfileOptionKeyDown = useCallback(
    (
      section: DesktopProfileSection,
      index: number,
      event: React.KeyboardEvent<HTMLButtonElement>,
    ): void => {
      const count =
        section === "model"
          ? selectableModelOptions.length
          : selectableEfforts.length;
      if (count === 0) {
        return;
      }
      if (
        event.key === "ArrowDown" ||
        event.key === "ArrowUp" ||
        event.key === "Home" ||
        event.key === "End"
      ) {
        event.preventDefault();
        const nextIndex =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? count - 1
              : (index + (event.key === "ArrowDown" ? 1 : -1) + count) % count;
        focusDesktopProfileOption(section, nextIndex);
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "Escape") {
        event.preventDefault();
        setDesktopProfileSection(null);
        focusDesktopProfileSection(section);
      }
    },
    [
      focusDesktopProfileOption,
      focusDesktopProfileSection,
      selectableEfforts.length,
      selectableModelOptions.length,
    ],
  );

  const handleProfileTriggerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>): void => {
      if (isMobile) {
        return;
      }
      if (event.key === "Escape" && profilePickerOpened) {
        event.preventDefault();
        closeDesktopProfilePicker();
        return;
      }
      if (
        event.key !== "ArrowDown" &&
        event.key !== "ArrowUp" &&
        event.key !== "Enter" &&
        event.key !== " "
      ) {
        return;
      }
      event.preventDefault();
      setProfilePickerOpened(true);
      setDesktopProfileSection(null);
      focusDesktopProfileSection(
        event.key === "ArrowUp" && selectableEfforts.length > 0
          ? "effort"
          : "model",
      );
    },
    [
      closeDesktopProfilePicker,
      focusDesktopProfileSection,
      isMobile,
      profilePickerOpened,
      selectableEfforts.length,
    ],
  );

  return {
    t,
    agentId,
    sessionId,
    isMobile,
    selectableModelOptions,
    defaultInferenceProfile,
    inferenceProfileSelectionEnabled,
    contextUsageEnabled,
    contextUsage,
    contextUsageActiveRun,
    onApplyInferenceProfile,
    isUploading,
    pendingFiles,
    goal,
    todo,
    onClearGoal,
    onUpdateGoal,
    onPauseGoal,
    onResumeGoal,
    removeFile,
    wasCommandBlocked,
    isStopAvailable,
    isStopPending,
    onStopRequest,
    editingMessageId,
    editSendDisabled,
    inputDisabled,
    disabledPlaceholder,
    inputValue,
    inferenceProfile,
    profilePickerOpened,
    setProfilePickerOpened,
    scrollToContextUsageOnOpen,
    setScrollToContextUsageOnOpen,
    contextUsageDetailsRef,
    desktopProfileSection,
    setDesktopProfileSection,
    sendErrorVisible,
    selectedAction,
    setSelectedAction,
    inputActionListboxId,
    inputActionOptionRefs,
    desktopProfileDialogId,
    desktopProfileModelPanelId,
    desktopProfileEffortPanelId,
    profileTriggerRef,
    desktopProfileSectionRefs,
    desktopModelOptionRefs,
    desktopEffortOptionRefs,
    selectableEfforts,
    selectedModelLabel,
    selectedEffortLabel,
    hasPendingInferenceProfileChange,
    fileInputRef,
    textareaRef,
    inputActionQuery,
    visibleInputActions,
    todoPreviewVisible,
    activeInputActionIndex,
    setActiveInputActionIndex,
    activeInputAction,
    activeInputActionOptionId,
    updateInputValue,
    persistDraft,
    handleCancelEdit,
    handleSend,
    handleSelectInputAction,
    handleInputFocus,
    handleInputBlur,
    handleKeyDown,
    handleFileChange,
    handleModelChange,
    handleEffortChange,
    handleOpenContextUsage,
    handleProfilePickerEnterTransitionEnd,
    desktopProfileSections,
    closeDesktopProfilePicker,
    handleDesktopProfileSectionKeyDown,
    handleDesktopProfileOptionKeyDown,
    handleProfileTriggerKeyDown,
  };
}

export type ChatInputContainer = ReturnType<
  typeof useChatInputContainerImplementation
>;

export function useChatInputContainer(
  props: ChatInputProps,
): ChatInputContainer {
  return useChatInputContainerImplementation(props);
}
