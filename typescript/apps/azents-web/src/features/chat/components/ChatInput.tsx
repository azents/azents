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
  Divider,
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
import { readLocalStorageValue, useLocalStorage } from "@mantine/hooks";
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
import {
  memo,
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
import { AttachmentPreviewBar } from "./AttachmentPreviewBar";
import classes from "./ChatInput.module.css";
import { TodoPreviewBar } from "./TodoPreviewBar";
import { TokenUsageDetails, TokenUsageIndicator } from "./TokenUsageIndicator";
import type { PendingFile, UploadedFile } from "../hooks/useFileUpload";
import type {
  ChatAction,
  ChatLiveRunState,
  GoalStateSnapshot,
  InputActionDefinition,
  TodoStateSnapshot,
  TokenUsageSummary,
} from "../types";
import type {
  AgentResponse,
  ModelReasoningEffort,
  RequestedInferenceProfile,
} from "@azents/public-client";

const DRAFT_STORAGE_KEY_PREFIX = "azents.chat.inputDraft";
const LAST_SELECTED_PROFILE_STORAGE_KEY_PREFIX =
  "azents.chat.lastSelectedInferenceProfile";

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
  /** whether the model and reasoning-effort picker is available */
  inferenceProfileSelectionEnabled?: boolean;
  /** whether context-window usage is shown below the model picker */
  contextUsageEnabled?: boolean;
  /** latest context-window usage snapshot */
  contextUsage?: TokenUsageSummary | null;
  /** active run used to resolve transient inference provenance */
  contextUsageActiveRun?: ChatLiveRunState | null;
  /** notifies the owning session when the effective composer profile changes */
  onInferenceProfileChange?: (profile: RequestedInferenceProfile) => void;
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
  inferenceProfile: RequestedInferenceProfile | null;
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
  if (action.type === "cleanup_orphan_git_worktrees") {
    return { type: "cleanup_orphan_git_worktrees" };
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
  inferenceProfile: RequestedInferenceProfile | null,
): string {
  return JSON.stringify({
    message,
    action,
    inference_profile: inferenceProfile,
  });
}

function parseStoredInferenceProfile(
  raw: string,
): RequestedInferenceProfile | null {
  if (!raw) {
    return null;
  }
  try {
    return normalizeStoredInferenceProfile(JSON.parse(raw));
  } catch {
    return null;
  }
}

function serializeInferenceProfile(
  inferenceProfile: RequestedInferenceProfile,
): string {
  return JSON.stringify(inferenceProfile);
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

function profileTargetExists(
  profile: RequestedInferenceProfile | null,
  options: AgentResponse["selectable_model_options"],
): profile is RequestedInferenceProfile {
  return (
    profile !== null &&
    options.some((option) => option.label === profile.model_target_label)
  );
}

function restoreInferenceProfile(
  draftProfile: RequestedInferenceProfile | null,
  lastSelectedProfile: RequestedInferenceProfile | null,
  options: AgentResponse["selectable_model_options"],
  fallback: RequestedInferenceProfile,
): RequestedInferenceProfile {
  if (profileTargetExists(draftProfile, options)) {
    return draftProfile;
  }
  if (profileTargetExists(lastSelectedProfile, options)) {
    return lastSelectedProfile;
  }
  return normalizeProfileForOptions(null, options, fallback);
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
  inferenceProfileSelectionEnabled = true,
  contextUsageEnabled = false,
  contextUsage = null,
  contextUsageActiveRun = null,
  onInferenceProfileChange,
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
    () => getScopedStorageKey(DRAFT_STORAGE_KEY_PREFIX, agentId, sessionId),
    [agentId, sessionId],
  );
  const lastSelectedProfileStorageKey = useMemo(
    () =>
      getScopedStorageKey(
        LAST_SELECTED_PROFILE_STORAGE_KEY_PREFIX,
        agentId,
        sessionId,
      ),
    [agentId, sessionId],
  );
  const storageKey =
    draftStorageKey ?? `${DRAFT_STORAGE_KEY_PREFIX}.__disabled`;
  const lastSelectedStorageKey =
    lastSelectedProfileStorageKey ??
    `${LAST_SELECTED_PROFILE_STORAGE_KEY_PREFIX}.__disabled`;
  const [draftValue, setDraftValue, clearStoredDraft] = useLocalStorage<string>(
    {
      key: storageKey,
      defaultValue: "",
    },
  );
  const [
    lastSelectedProfileValue,
    setLastSelectedProfileValue,
    clearLastSelectedProfile,
  ] = useLocalStorage<string>({
    key: lastSelectedStorageKey,
    defaultValue: "",
  });
  const parsedDraft = useMemo(
    () => parseComposerDraft(draftValue),
    [draftValue],
  );
  const storedLastSelectedProfile = useMemo(
    () => parseStoredInferenceProfile(lastSelectedProfileValue),
    [lastSelectedProfileValue],
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
  const restoredInferenceProfile = useMemo(
    () =>
      restoreInferenceProfile(
        parsedDraft.inferenceProfile,
        storedLastSelectedProfile,
        selectableModelOptions,
        normalizedDefaultProfile,
      ),
    [
      normalizedDefaultProfile,
      parsedDraft.inferenceProfile,
      selectableModelOptions,
      storedLastSelectedProfile,
    ],
  );
  const restoredComposerInferenceProfile = inferenceProfileSelectionEnabled
    ? restoredInferenceProfile
    : normalizedDefaultProfile;
  const [inputValue, setInputValue] = useState(
    initialInputValue ?? parsedDraft.message,
  );
  const [inferenceProfile, setInferenceProfile] = useState(
    restoredComposerInferenceProfile,
  );
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
    onInferenceProfileChange?.(inferenceProfile);
  }, [inferenceProfile, onInferenceProfileChange]);

  useEffect(() => {
    if (selectableModelOptions.length === 0) {
      return;
    }
    if (draftStorageKey) {
      const currentDraft = parseComposerDraft(
        readLocalStorageValue<string>({
          key: draftStorageKey,
          defaultValue: "",
        }),
      );
      if (
        currentDraft.inferenceProfile !== null &&
        !profileTargetExists(
          currentDraft.inferenceProfile,
          selectableModelOptions,
        )
      ) {
        setDraftValue(
          serializeComposerDraft(
            currentDraft.message,
            currentDraft.action,
            null,
          ),
        );
      }
    }
    if (lastSelectedProfileStorageKey) {
      const currentLastSelectedProfile = parseStoredInferenceProfile(
        readLocalStorageValue<string>({
          key: lastSelectedProfileStorageKey,
          defaultValue: "",
        }),
      );
      if (
        currentLastSelectedProfile !== null &&
        !profileTargetExists(currentLastSelectedProfile, selectableModelOptions)
      ) {
        clearLastSelectedProfile();
      }
    }
  }, [
    clearLastSelectedProfile,
    draftStorageKey,
    lastSelectedProfileStorageKey,
    selectableModelOptions,
    setDraftValue,
  ]);

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
    setInferenceProfile(restoredComposerInferenceProfile);
  }, [
    editingMessageId,
    initialInputValue,
    inputActions,
    normalizedDefaultProfile,
    parsedDraft,
    restoredComposerInferenceProfile,
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

  const persistLastSelectedProfile = useCallback(
    (profile: RequestedInferenceProfile): void => {
      if (editingMessageId !== null || !lastSelectedProfileStorageKey) {
        return;
      }
      setLastSelectedProfileValue(serializeInferenceProfile(profile));
    },
    [
      editingMessageId,
      lastSelectedProfileStorageKey,
      setLastSelectedProfileValue,
    ],
  );

  const updateInputValue = useCallback(
    (nextValue: string): void => {
      setSendErrorVisible(false);
      setInputActionSuggestionsDismissed(false);
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
    setInferenceProfile(restoredComposerInferenceProfile);
  }, [inputActions, parsedDraft, restoredComposerInferenceProfile]);

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
      persistLastSelectedProfile(inferenceProfile);
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
    inferenceProfile,
    onAfterSend,
    persistLastSelectedProfile,
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
      persistDraft(message, normalizedAction, inferenceProfile);
      textareaRef.current?.focus();
    },
    [inferenceProfile, inputValue, persistDraft],
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
    [
      activeInputAction,
      handleSelectInputAction,
      handleSend,
      isMobile,
      visibleInputActions,
    ],
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

  const updateInferenceProfile = useCallback(
    (nextProfile: RequestedInferenceProfile): void => {
      setInferenceProfile(nextProfile);
      persistDraft(
        inputValue,
        selectedAction === null ? null : normalizeAction(selectedAction.action),
        nextProfile,
      );
      persistLastSelectedProfile(nextProfile);
    },
    [inputValue, persistDraft, persistLastSelectedProfile, selectedAction],
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

  const profileTrigger = (
    <Button
      variant="light"
      size="compact-sm"
      radius={rem(12)}
      disabled={inputDisabled || selectableModelOptions.length === 0}
      ref={profileTriggerRef}
      onClick={() => {
        setProfilePickerOpened(!profilePickerOpened);
        if (profilePickerOpened) {
          setDesktopProfileSection(null);
        }
      }}
      onKeyDown={handleProfileTriggerKeyDown}
      rightSection={<IconChevronDown aria-hidden="true" size={14} />}
      aria-label={t("composerProfile.model")}
      {...(!isMobile
        ? {
            "aria-controls": desktopProfileDialogId,
            "aria-expanded": profilePickerOpened,
            "aria-haspopup": "dialog" as const,
          }
        : {})}
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
  const contextUsageTrigger = contextUsageEnabled ? (
    <TokenUsageIndicator usage={contextUsage} onOpen={handleOpenContextUsage} />
  ) : null;
  const modelOptionRows = selectableModelOptions.map((option, index) => {
    const selected = option.label === inferenceProfile.model_target_label;
    return (
      <UnstyledButton
        key={option.label}
        ref={(node) => {
          if (node === null) {
            desktopModelOptionRefs.current.delete(index);
          } else {
            desktopModelOptionRefs.current.set(index, node);
          }
        }}
        onClick={() => handleModelChange(option.label)}
        onKeyDown={(event) => {
          if (!isMobile) {
            handleDesktopProfileOptionKeyDown("model", index, event);
          }
        }}
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
        ref={(node) => {
          if (node === null) {
            desktopEffortOptionRefs.current.delete(index);
          } else {
            desktopEffortOptionRefs.current.set(index, node);
          }
        }}
        onClick={() => handleEffortChange(effort)}
        onKeyDown={(event) => {
          if (!isMobile) {
            handleDesktopProfileOptionKeyDown("effort", index, event);
          }
        }}
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
      {inferenceProfileSelectionEnabled ? (
        <>
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
          {selectableEfforts.length > 0 ? (
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
          ) : null}
        </>
      ) : null}
      {contextUsageEnabled ? (
        <Box ref={contextUsageDetailsRef}>
          {inferenceProfileSelectionEnabled ? <Divider mb="sm" /> : null}
          <TokenUsageDetails
            activeRun={contextUsageActiveRun}
            usage={contextUsage}
          />
        </Box>
      ) : null}
    </Stack>
  );
  const desktopProfileMenu = (
    <Group gap={rem(4)} align="flex-end" wrap="nowrap">
      <Paper
        id={desktopProfileDialogId}
        role="dialog"
        aria-label={t("composerProfile.model")}
        withBorder
        radius={rem(12)}
        shadow="md"
        p={rem(6)}
        w={rem(260)}
        style={{ maxHeight: "70dvh", overflowY: "auto" }}
      >
        <Stack gap={rem(2)}>
          {contextUsageEnabled ? (
            <>
              <Box ref={contextUsageDetailsRef} px={rem(10)} pb={rem(6)}>
                <TokenUsageDetails
                  activeRun={contextUsageActiveRun}
                  usage={contextUsage}
                />
              </Box>
              {inferenceProfileSelectionEnabled ? <Divider my="xs" /> : null}
            </>
          ) : null}
          {inferenceProfileSelectionEnabled ? (
            <>
              <UnstyledButton
                ref={(node) => {
                  if (node === null) {
                    desktopProfileSectionRefs.current.delete("model");
                  } else {
                    desktopProfileSectionRefs.current.set("model", node);
                  }
                }}
                onMouseEnter={() => setDesktopProfileSection("model")}
                onClick={() => setDesktopProfileSection("model")}
                onKeyDown={(event) =>
                  handleDesktopProfileSectionKeyDown("model", event)
                }
                aria-expanded={desktopProfileSection === "model"}
                aria-controls={desktopProfileModelPanelId}
                aria-haspopup="true"
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
                  ref={(node) => {
                    if (node === null) {
                      desktopProfileSectionRefs.current.delete("effort");
                    } else {
                      desktopProfileSectionRefs.current.set("effort", node);
                    }
                  }}
                  onMouseEnter={() => setDesktopProfileSection("effort")}
                  onClick={() => setDesktopProfileSection("effort")}
                  onKeyDown={(event) =>
                    handleDesktopProfileSectionKeyDown("effort", event)
                  }
                  aria-expanded={desktopProfileSection === "effort"}
                  aria-controls={desktopProfileEffortPanelId}
                  aria-haspopup="true"
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
            </>
          ) : null}
        </Stack>
      </Paper>
      {inferenceProfileSelectionEnabled &&
        desktopProfileSection === "model" && (
          <Paper
            id={desktopProfileModelPanelId}
            role="group"
            aria-label={t("composerProfile.model")}
            withBorder
            radius={rem(12)}
            shadow="md"
            w={rem(280)}
            style={{ maxHeight: rem(280), overflowY: "auto" }}
          >
            <Stack gap={0}>{modelOptionRows}</Stack>
          </Paper>
        )}
      {inferenceProfileSelectionEnabled &&
        desktopProfileSection === "effort" &&
        selectableEfforts.length > 0 && (
          <Paper
            id={desktopProfileEffortPanelId}
            role="group"
            aria-label={t("composerProfile.effortLabel")}
            withBorder
            radius={rem(12)}
            shadow="md"
            p={rem(6)}
            w={rem(220)}
          >
            <Text size="xs" c="dimmed" fw={600} px={rem(8)} py={rem(4)}>
              {t("composerProfile.effortLabel")}
            </Text>
            <Stack gap={rem(2)}>
              {selectableEfforts.map((effort, index) => {
                const selected = effort === inferenceProfile.reasoning_effort;
                return (
                  <UnstyledButton
                    key={effort}
                    ref={(node) => {
                      if (node === null) {
                        desktopEffortOptionRefs.current.delete(index);
                      } else {
                        desktopEffortOptionRefs.current.set(index, node);
                      }
                    }}
                    onClick={() => handleEffortChange(effort)}
                    onKeyDown={(event) =>
                      handleDesktopProfileOptionKeyDown("effort", index, event)
                    }
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
            id={inputActionListboxId}
            role="listbox"
            aria-label={t("slashCommands.title")}
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
              {visibleInputActions.map((ranked, index) => (
                <UnstyledButton
                  key={ranked.action.id}
                  ref={(node) => {
                    if (node === null) {
                      inputActionOptionRefs.current.delete(index);
                    } else {
                      inputActionOptionRefs.current.set(index, node);
                    }
                  }}
                  id={`${inputActionListboxId}-option-${index}`}
                  role="option"
                  aria-selected={index === activeInputActionIndex}
                  tabIndex={-1}
                  onClick={() => handleSelectInputAction(ranked.action)}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseMove={() => setActiveInputActionIndex(index)}
                  px="xs"
                  py={rem(7)}
                  style={{
                    background:
                      index === activeInputActionIndex
                        ? "var(--mantine-color-default-hover)"
                        : "transparent",
                    borderRadius: rem(8),
                    width: "100%",
                  }}
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
              name="message"
              inputMode="text"
              autoCorrect="on"
              autoCapitalize="sentences"
              spellCheck
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
              onFocus={handleInputFocus}
              onBlur={handleInputBlur}
              aria-autocomplete={inputActionQuery === null ? void 0 : "list"}
              aria-controls={
                visibleInputActions.length > 0 ? inputActionListboxId : void 0
              }
              aria-expanded={visibleInputActions.length > 0}
              aria-haspopup="listbox"
              aria-activedescendant={
                activeInputAction === null ? void 0 : activeInputActionOptionId
              }
              disabled={inputDisabled}
              autosize
              minRows={1}
              maxRows={5}
              classNames={{ input: classes.composerTextarea }}
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
                  {inferenceProfileSelectionEnabled ? profileTrigger : null}
                  {contextUsageTrigger}
                  {inferenceProfileSelectionEnabled || contextUsageEnabled ? (
                    <Drawer
                      opened={profilePickerOpened}
                      onClose={() => {
                        setProfilePickerOpened(false);
                        setScrollToContextUsageOnOpen(false);
                      }}
                      transitionProps={{
                        onEntered: handleProfilePickerEnterTransitionEnd,
                      }}
                      title={
                        inferenceProfileSelectionEnabled
                          ? t("composerProfile.model")
                          : t("tokenUsage.title")
                      }
                      closeButtonProps={{
                        "aria-label": t("composerProfile.done"),
                        icon: (
                          <Text component="span" size="sm" fw={500}>
                            {t("composerProfile.done")}
                          </Text>
                        ),
                        onClick: () => setScrollToContextUsageOnOpen(false),
                        style: {
                          color: "var(--mantine-color-blue-6)",
                          paddingInline: rem(8),
                          width: "auto",
                        },
                      }}
                      position="bottom"
                      size={`min(80dvh, ${rem(720)})`}
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
                  ) : null}
                </>
              ) : inferenceProfileSelectionEnabled || contextUsageEnabled ? (
                <Popover
                  opened={profilePickerOpened}
                  onChange={(opened) => {
                    setProfilePickerOpened(opened);
                    if (!opened) {
                      setDesktopProfileSection(null);
                      setScrollToContextUsageOnOpen(false);
                    }
                  }}
                  position="top-start"
                  width="auto"
                  shadow="none"
                  withinPortal
                >
                  <Popover.Target>
                    <Group gap="xs" wrap="nowrap">
                      {inferenceProfileSelectionEnabled ? profileTrigger : null}
                      {contextUsageTrigger}
                    </Group>
                  </Popover.Target>
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
              ) : null}
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
