"use client";

import { useLocalStorage, useSessionStorage } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import {
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { isRecord } from "@/shared/lib/unknown-value";
import { completedCompactionIds } from "../compactionPresentation";
import {
  captureChatScrollAnchor,
  type ChatScrollAnchor,
  restorePrependScrollTop,
} from "../hooks/chatScrollAnchor";
import {
  type PendingFile,
  type UploadedFile,
  useFileUpload,
} from "../hooks/useFileUpload";
import {
  projectChatPresentationItems,
  type ToolActivityGroup as ToolActivityGroupModel,
} from "../toolActivityPresentation";
import type { PendingMailboxEntry } from "../hooks/pendingMailboxState";
import type { CurrentWorkspaceProfile } from "../senderPresentation";
import type {
  ActionExecutionProjection,
  AuthorizationRequest,
  ChatAction,
  ChatLiveRunState,
  ChatMessage,
  ChatTimelineState,
  ChatViewState,
  GoalStateSnapshot,
  InputActionDefinition,
  PendingInputBuffer,
  TodoStateSnapshot,
  TokenUsageSummary,
} from "../types";
import type { WorkspacePanelContainerOutput } from "../workspace/containers/useWorkspacePanelContainer";
import type {
  AgentResponse,
  ChatEventResponse,
  RequestedInferenceProfile,
} from "@azents/public-client";
const LOAD_MORE_THRESHOLD = 100;
const BOTTOM_FOLLOW_THRESHOLD = 48;
const PROGRAMMATIC_SCROLL_GUARD_MS = 350;
const LOAD_MORE_COOLDOWN_MS = 800;
const CHAT_SCROLL_STATE_STORAGE_PREFIX = "azents.chat.scrollState.";
const KEYBOARD_RESIZE_SETTLE_MS = 250;
const WORKSPACE_RATIO_STORAGE_KEY = "azents.chat.workspaceRatio";
const DEFAULT_CHAT_RATIO = 0.55;
const MIN_CHAT_RATIO = 0.35;
const MAX_CHAT_RATIO = 0.75;
function scrollDistanceFromBottom(viewport: HTMLDivElement): number {
  const { scrollTop, scrollHeight, clientHeight } = viewport;
  return Math.max(0, scrollHeight - scrollTop - clientHeight);
}

function visibleTimelineItem(viewport: HTMLDivElement): HTMLElement | null {
  const viewportRect = viewport.getBoundingClientRect();
  const items = viewport.querySelectorAll<HTMLElement>(
    "[data-chat-scroll-anchor]",
  );
  for (const item of items) {
    const itemRect = item.getBoundingClientRect();
    if (
      itemRect.bottom > viewportRect.top &&
      itemRect.top < viewportRect.bottom
    ) {
      return item;
    }
  }
  return null;
}

interface StoredChatScrollState {
  distanceFromBottom: number;
  following: boolean;
}

function parseStoredChatScrollState(
  raw: string | null,
): StoredChatScrollState | null {
  if (raw === null) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) {
      return null;
    }
    if (
      typeof parsed.distanceFromBottom === "number" &&
      typeof parsed.following === "boolean"
    ) {
      return {
        distanceFromBottom: parsed.distanceFromBottom,
        following: parsed.following,
      };
    }
  } catch {
    return null;
  }
  return null;
}

export interface EditingMessageState {
  messageId: string;
  content: string;
  inferenceProfile: RequestedInferenceProfile | null;
}
export function isBoundaryMessage(message: ChatMessage): boolean {
  return message.role === "turn_complete" || message.role === "run_complete";
}
function isVisibleMessageAnchor(message: ChatMessage): boolean {
  return (
    !isBoundaryMessage(message) &&
    message.role !== "compaction_started" &&
    message.role !== "compaction"
  );
}

function latestVisibleMessageId(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message && isVisibleMessageAnchor(message)) {
      return message.id;
    }
  }
  return null;
}

function latestUserMessageIndex(messages: ChatMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "user") {
      return index;
    }
  }
  return -1;
}

function activeRunActivity(
  runId: string,
  source: ToolActivityGroupModel | null,
): ToolActivityGroupModel {
  if (source !== null) {
    return { ...source, id: `activity:run:${runId}` };
  }
  return {
    id: `activity:run:${runId}`,
    firstMessageId: `run:${runId}`,
    startedAt: null,
    startMessageIndex: 0,
    endMessageIndex: 0,
    events: [],
    usage: null,
  };
}

function hasLiveRetry(
  liveRun: ChatLiveRunState | null,
): liveRun is ChatLiveRunState & {
  retry: NonNullable<ChatLiveRunState["retry"]>;
} {
  return liveRun?.retry !== null && typeof liveRun?.retry !== "undefined";
}

function hasLiveOperation(
  liveRun: ChatLiveRunState | null,
): liveRun is ChatLiveRunState & {
  operation: NonNullable<ChatLiveRunState["operation"]>;
} {
  return (
    liveRun?.operation !== null && typeof liveRun?.operation !== "undefined"
  );
}
function getLatestCompactionIndex(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === "compaction") {
      return i;
    }
  }
  return -1;
}

function actionExecutionTimelineItemId(
  actionExecution: ActionExecutionProjection,
): string {
  return `action:${actionExecution.execution.id}`;
}

function compareTimelineKeys(
  leftTime: string,
  leftId: string,
  rightTime: string,
  rightId: string,
): number {
  const byTime = leftTime.localeCompare(rightTime);
  return byTime === 0 ? leftId.localeCompare(rightId) : byTime;
}

export interface ActionExecutionTimelinePlacement {
  durableBeforeMessage: Map<string, ActionExecutionProjection[]>;
  durableTail: ActionExecutionProjection[];
  liveTail: ActionExecutionProjection[];
}

function placeActionExecutions(
  messages: ChatMessage[],
  actionExecutions: ActionExecutionProjection[],
): ActionExecutionTimelinePlacement {
  const durableBeforeMessage = new Map<string, ActionExecutionProjection[]>();
  const durableTail: ActionExecutionProjection[] = [];
  const durable = actionExecutions
    .filter((projection) => projection.provenance === "durable")
    .sort((left, right) =>
      compareTimelineKeys(
        left.historyCreatedAt ?? left.execution.updated_at,
        left.historyEventId ?? left.execution.id,
        right.historyCreatedAt ?? right.execution.updated_at,
        right.historyEventId ?? right.execution.id,
      ),
    );
  const liveTail = actionExecutions
    .filter((projection) => projection.provenance === "live")
    .sort((left, right) =>
      compareTimelineKeys(
        left.execution.updated_at,
        left.execution.id,
        right.execution.updated_at,
        right.execution.id,
      ),
    );

  for (const actionExecution of durable) {
    const followingMessage = messages.find(
      (message) =>
        compareTimelineKeys(
          actionExecution.historyCreatedAt ??
            actionExecution.execution.updated_at,
          actionExecution.historyEventId ?? actionExecution.execution.id,
          message.createdAt,
          message.id,
        ) < 0,
    );
    if (!followingMessage) {
      durableTail.push(actionExecution);
      continue;
    }
    const before = durableBeforeMessage.get(followingMessage.id) ?? [];
    durableBeforeMessage.set(followingMessage.id, [...before, actionExecution]);
  }

  return { durableBeforeMessage, durableTail, liveTail };
}
function getTimelineItemIds(
  messages: ChatMessage[],
  pendingInputBuffers: PendingInputBuffer[],
  liveRun: ChatLiveRunState | null,
  actionExecutions: ActionExecutionProjection[],
): string[] {
  const placement = placeActionExecutions(messages, actionExecutions);
  const ids: string[] = [];

  for (const message of messages) {
    for (const actionExecution of placement.durableBeforeMessage.get(
      message.id,
    ) ?? []) {
      ids.push(actionExecutionTimelineItemId(actionExecution));
    }
    ids.push(`message:${message.id}`);
  }
  for (const actionExecution of placement.durableTail) {
    ids.push(actionExecutionTimelineItemId(actionExecution));
  }
  if (hasLiveRetry(liveRun)) {
    ids.push(`live-run-retry:${liveRun.run_id}`);
  }
  if (hasLiveOperation(liveRun)) {
    ids.push(`live-run-operation:${liveRun.operation.operationId}`);
  }
  for (const actionExecution of placement.liveTail) {
    ids.push(actionExecutionTimelineItemId(actionExecution));
  }
  for (const buffer of pendingInputBuffers) {
    ids.push(`pending:${buffer.id}`);
  }

  return ids;
}

export interface ChatViewProps {
  chatViewState: ChatViewState;
  chatTimelineState: ChatTimelineState;
  messages: ChatMessage[];
  timelineEvents: ChatEventResponse[];
  pendingInputBuffers: PendingInputBuffer[];
  pendingMailboxEntries?: PendingMailboxEntry[];
  activeAgent: AgentResponse | null;
  appliedInferenceProfile?: RequestedInferenceProfile | null;
  defaultInferenceProfile: RequestedInferenceProfile;
  sessionId?: string | null;
  isResponsePending: boolean;
  isModelResponsePending: boolean;
  isWritePending: boolean;
  lastEventReceivedAt: string | null;
  liveRun: ChatLiveRunState | null;
  onApplyInferenceProfile?: (
    profile: RequestedInferenceProfile,
  ) => Promise<boolean>;
  tokenUsage?: TokenUsageSummary | null;
  onSendInput: (
    message: string,
    action: ChatAction | null,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  onDeletePendingInputBuffer: (bufferId: string) => void;
  onClearGoal: () => Promise<boolean>;
  onUpdateGoal: (objective: string) => Promise<boolean>;
  onPauseGoal: () => Promise<boolean>;
  onResumeGoal: (hint?: string) => Promise<boolean>;
  hasMore: boolean;
  isLoadingMore: boolean;
  isLoadingNewer: boolean;
  onLoadMore: (options?: { detachFromLatest?: boolean }) => void;
  onLoadNewer: () => void;
  onResetToLatest: () => void;
  onSubmitMessageEdit: (
    messageId: string,
    message: string,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  onRetryFailedRun: (failedEventId: string) => Promise<boolean>;
  wasCommandBlocked: boolean;
  isStopAvailable: boolean;
  isStopPending: boolean;
  onStopRequest: () => void;
  inputActions: InputActionDefinition[];
  authorizationRequests: AuthorizationRequest[];
  onAuthorizationComplete: (toolkitId: string) => void;
  actionExecutions: ActionExecutionProjection[];
  workspacePanel: WorkspacePanelContainerOutput;
  goal: GoalStateSnapshot;
  todo: TodoStateSnapshot;
  currentWorkspaceProfile?: CurrentWorkspaceProfile | null;
  readOnlyNotice?: string | null;
}

type RequiredChatViewProps = Omit<
  ChatViewProps,
  | "appliedInferenceProfile"
  | "sessionId"
  | "tokenUsage"
  | "pendingMailboxEntries"
  | "currentWorkspaceProfile"
  | "readOnlyNotice"
> & {
  appliedInferenceProfile: RequestedInferenceProfile | null;
  sessionId: string | null;
  tokenUsage: TokenUsageSummary | null;
  pendingMailboxEntries: PendingMailboxEntry[];
  currentWorkspaceProfile: CurrentWorkspaceProfile | null;
  readOnlyNotice: string | null;
};

type ChatPresentationItem = ReturnType<
  typeof projectChatPresentationItems
>[number];
type ActivityPresentationItem = Extract<
  ChatPresentationItem,
  { type: "activity" }
>;

export type ChatViewContainerOutput = RequiredChatViewProps & {
  t: ReturnType<typeof useTranslations>;
  scrollAreaRef: RefObject<HTMLDivElement | null>;
  viewportRef: RefObject<HTMLDivElement | null>;
  contentRef: RefObject<HTMLDivElement | null>;
  splitContainerRef: RefObject<HTMLDivElement | null>;
  pendingFiles: PendingFile[];
  addFiles: (files: FileList | File[]) => void;
  removeFile: (id: string) => void;
  clearFiles: () => void;
  resetDoneFiles: () => void;
  uploadAll: (agentId: string) => Promise<UploadedFile[]>;
  isUploading: boolean;
  showNewMessageChip: boolean;
  chatRatio: number;
  editingMessage: EditingMessageState | null;
  isMobile: boolean;
  latestCompactionIndex: number;
  completedCompactionIdSet: ReadonlySet<string>;
  hasDetachedNewer: boolean;
  latestVisibleId: string | null;
  latestActivityId: string | null;
  liveRetryRun:
    | (ChatLiveRunState & {
        retry: NonNullable<ChatLiveRunState["retry"]>;
      })
    | null;
  liveOperationRun: ChatLiveRunState | null;
  activeRun: ChatLiveRunState | null;
  visibleActionExecutions: ActionExecutionProjection[];
  actionExecutionPlacement: ActionExecutionTimelinePlacement;
  chatPresentationItems: ChatPresentationItem[];
  activeActivitySource: ActivityPresentationItem | null;
  activeActivity: ToolActivityGroupModel | null;
  attachedAuthorizationRequest: AuthorizationRequest | null;
  unattachedAuthorizationRequests: AuthorizationRequest[];
  hasTimelineItems: boolean;
  editingMessageIndex: number | null;
  handleStartEdit: (message: ChatMessage) => void;
  handleCancelEdit: () => void;
  handleSubmitInput: (
    message: string,
    action: ChatAction | null,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  handleWorkspaceResizeStart: (
    event: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  scrollToBottom: () => void;
  handleInputFocus: () => void;
  handleAfterSend: () => void;
};

export function useChatViewContainer({
  chatViewState,
  chatTimelineState,
  messages,
  timelineEvents,
  pendingInputBuffers,
  pendingMailboxEntries = [],
  activeAgent,
  appliedInferenceProfile = null,
  defaultInferenceProfile,
  sessionId = null,
  isResponsePending,
  isModelResponsePending,
  isWritePending,
  lastEventReceivedAt,
  liveRun,
  onApplyInferenceProfile,
  tokenUsage = null,
  onSendInput,
  onDeletePendingInputBuffer,
  onClearGoal,
  onUpdateGoal,
  onPauseGoal,
  onResumeGoal,
  hasMore,
  isLoadingMore,
  isLoadingNewer,
  onLoadMore,
  onLoadNewer,
  onResetToLatest,
  onSubmitMessageEdit,
  onRetryFailedRun,
  wasCommandBlocked,
  isStopAvailable,
  isStopPending,
  onStopRequest,
  inputActions,
  authorizationRequests,
  onAuthorizationComplete,
  actionExecutions,
  workspacePanel,
  goal,
  todo,
  currentWorkspaceProfile = null,
  readOnlyNotice = null,
}: ChatViewProps): ChatViewContainerOutput {
  const t = useTranslations("chat");
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const isInitialScrollRef = useRef(true);
  const {
    pendingFiles,
    addFiles,
    removeFile,
    clearFiles,
    resetDoneFiles,
    uploadAll,
    isUploading,
  } = useFileUpload();
  const isFollowingLatestRef = useRef(true);
  const [showNewMessageChip, setShowNewMessageChip] = useState(false);
  const prevMessageIdsRef = useRef<Set<string>>(new Set());
  const isReadyForPaginationRef = useRef(false);

  const [chatRatio, setChatRatio] = useLocalStorage<number>({
    key: WORKSPACE_RATIO_STORAGE_KEY,
    defaultValue: DEFAULT_CHAT_RATIO,
    deserialize: (value?: string): number => {
      const parsed = Number.parseFloat(value ?? "");
      if (!Number.isFinite(parsed)) {
        return DEFAULT_CHAT_RATIO;
      }
      return Math.min(MAX_CHAT_RATIO, Math.max(MIN_CHAT_RATIO, parsed));
    },
    serialize: (value: number): string => value.toString(),
  });
  const scrollStorageKey = `${CHAT_SCROLL_STATE_STORAGE_PREFIX}${sessionId ?? "__disabled"}`;
  const [storedScrollState, setStoredScrollState] =
    useSessionStorage<StoredChatScrollState | null>({
      key: scrollStorageKey,
      defaultValue: null,
      deserialize: (value?: string): StoredChatScrollState | null =>
        parseStoredChatScrollState(value ?? null),
      serialize: (value: StoredChatScrollState | null): string =>
        JSON.stringify(value),
    });
  const [editingMessage, setEditingMessage] =
    useState<EditingMessageState | null>(null);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const programmaticScrollUntilRef = useRef(0);
  const detachedScrollRestoreUntilRef = useRef(0);
  const userScrollIntentGenerationRef = useRef(0);
  const lastLoadMoreTriggerAtRef = useRef(0);
  const previousSessionIdRef = useRef<string | null>(null);
  const pendingInitialScrollRestoreRef = useRef<StoredChatScrollState | null>(
    null,
  );
  const isMobile = useMemo(
    () =>
      typeof window !== "undefined" &&
      ("ontouchstart" in window || navigator.maxTouchPoints > 0),
    [],
  );
  const latestCompactionIndex = useMemo(
    () => getLatestCompactionIndex(messages),
    [messages],
  );
  const completedCompactionIdSet = useMemo(
    () => completedCompactionIds(messages),
    [messages],
  );
  const hasDetachedNewer =
    chatTimelineState.type === "DETACHED_HISTORY_BROWSING" &&
    chatTimelineState.hasNewer;
  const latestVisibleId = useMemo(
    () => latestVisibleMessageId(messages),
    [messages],
  );
  const liveRetryRun =
    chatTimelineState.type === "LATEST_FOLLOWING" && hasLiveRetry(liveRun)
      ? liveRun
      : null;
  const liveOperationRun =
    chatTimelineState.type === "LATEST_FOLLOWING" && hasLiveOperation(liveRun)
      ? liveRun
      : null;
  const liveRetryVisible = liveRetryRun !== null;
  const liveOperationVisible = liveOperationRun !== null;
  const activeRun =
    chatTimelineState.type === "LATEST_FOLLOWING" ? liveRun : null;
  const visibleActionExecutions = useMemo(
    () =>
      chatTimelineState.type === "LATEST_FOLLOWING"
        ? actionExecutions
        : actionExecutions.filter(
            (actionExecution) => actionExecution.provenance === "durable",
          ),
    [actionExecutions, chatTimelineState.type],
  );
  const actionExecutionPlacement = useMemo(
    () => placeActionExecutions(messages, visibleActionExecutions),
    [messages, visibleActionExecutions],
  );
  const actionBoundaryMessageIds = useMemo(
    () => new Set<string>(actionExecutionPlacement.durableBeforeMessage.keys()),
    [actionExecutionPlacement.durableBeforeMessage],
  );
  const chatPresentationItems = useMemo(
    () =>
      projectChatPresentationItems(
        timelineEvents,
        messages,
        actionBoundaryMessageIds,
      ),
    [actionBoundaryMessageIds, messages, timelineEvents],
  );
  const latestUserIndex = useMemo(
    () => latestUserMessageIndex(messages),
    [messages],
  );
  const latestActivityId = useMemo(() => {
    for (let index = chatPresentationItems.length - 1; index >= 0; index -= 1) {
      const item = chatPresentationItems[index];
      if (item?.type === "activity") {
        return item.id;
      }
    }
    return null;
  }, [chatPresentationItems]);
  const activeActivitySource = useMemo(() => {
    if (activeRun === null) {
      return null;
    }
    for (let index = chatPresentationItems.length - 1; index >= 0; index -= 1) {
      const item = chatPresentationItems[index];
      if (
        item?.type === "activity" &&
        item.activity.startMessageIndex > latestUserIndex
      ) {
        return item;
      }
    }
    return null;
  }, [activeRun, chatPresentationItems, latestUserIndex]);
  const activeActivity =
    activeRun === null
      ? null
      : activeRunActivity(
          activeRun.run_id,
          activeActivitySource?.activity ?? null,
        );
  const attachedAuthorizationRequest =
    latestActivityId === null ? null : (authorizationRequests[0] ?? null);
  const unattachedAuthorizationRequests =
    attachedAuthorizationRequest === null
      ? authorizationRequests
      : authorizationRequests.slice(1);
  const hasTimelineItems =
    messages.length > 0 ||
    pendingInputBuffers.length > 0 ||
    pendingMailboxEntries.length > 0 ||
    liveRetryVisible ||
    liveOperationVisible ||
    activeRun !== null ||
    visibleActionExecutions.length > 0;
  const editingMessageIndex = useMemo(() => {
    if (!editingMessage) {
      return null;
    }
    const index = messages.findIndex(
      (message) => message.id === editingMessage.messageId,
    );
    return index === -1 ? null : index;
  }, [editingMessage, messages]);

  const handleStartEdit = useCallback(
    (message: ChatMessage): void => {
      if (message.role !== "user" || !message.content) {
        return;
      }
      clearFiles();
      setEditingMessage({
        messageId: message.id,
        content: message.content,
        inferenceProfile: message.inferenceProfile ?? null,
      });
    },
    [clearFiles],
  );

  const handleCancelEdit = useCallback((): void => {
    setEditingMessage(null);
  }, []);

  const handleSubmitInput = useCallback(
    async (
      message: string,
      action: ChatAction | null,
      inferenceProfile: RequestedInferenceProfile,
      attachments?: UploadedFile[],
    ): Promise<boolean> => {
      if (!editingMessage) {
        return onSendInput(message, action, inferenceProfile, attachments);
      }
      if (isResponsePending || action) {
        return false;
      }
      const sent = await onSubmitMessageEdit(
        editingMessage.messageId,
        message,
        inferenceProfile,
        attachments,
      );
      if (sent) {
        setEditingMessage(null);
      }
      return sent;
    },
    [editingMessage, isResponsePending, onSendInput, onSubmitMessageEdit],
  );
  const isLoadingMoreRef = useRef(false);
  const lastAutoLoadAttemptKeyRef = useRef<string | null>(null);
  const savedScrollRef = useRef<ChatScrollAnchor | null>(null);
  const lastPersistedScrollStateRef = useRef<StoredChatScrollState | null>(
    null,
  );
  const lastPersistedScrollAtRef = useRef(0);

  const markProgrammaticScroll = useCallback((): void => {
    programmaticScrollUntilRef.current =
      performance.now() + PROGRAMMATIC_SCROLL_GUARD_MS;
  }, []);

  const markUserScrollIntent = useCallback((): void => {
    programmaticScrollUntilRef.current = 0;
    detachedScrollRestoreUntilRef.current = 0;
    userScrollIntentGenerationRef.current += 1;
    pendingInitialScrollRestoreRef.current = null;
  }, []);

  const persistScrollState = useCallback(
    (viewport: HTMLDivElement, following: boolean): void => {
      if (sessionId === null) {
        return;
      }
      const nextState: StoredChatScrollState = {
        distanceFromBottom: following ? 0 : scrollDistanceFromBottom(viewport),
        following,
      };
      const previousState = lastPersistedScrollStateRef.current;
      const now = performance.now();
      if (
        previousState !== null &&
        previousState.following === nextState.following &&
        now - lastPersistedScrollAtRef.current < PROGRAMMATIC_SCROLL_GUARD_MS
      ) {
        return;
      }
      lastPersistedScrollStateRef.current = nextState;
      lastPersistedScrollAtRef.current = now;
      setStoredScrollState(nextState);
    },
    [sessionId, setStoredScrollState],
  );

  const pinToBottom = useCallback((): void => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    markProgrammaticScroll();
    viewport.scrollTop = viewport.scrollHeight;
  }, [markProgrammaticScroll]);

  const schedulePinToBottom = useCallback((): void => {
    const userScrollIntentGeneration = userScrollIntentGenerationRef.current;
    requestAnimationFrame(() => {
      if (
        isFollowingLatestRef.current &&
        userScrollIntentGeneration === userScrollIntentGenerationRef.current
      ) {
        pinToBottom();
      }
    });
  }, [pinToBottom]);

  const handleWorkspaceResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>): void => {
      const container = splitContainerRef.current;
      if (!container) {
        return;
      }
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      const rect = container.getBoundingClientRect();
      const updateRatio = (clientX: number): void => {
        const rawRatio = (clientX - rect.left) / rect.width;
        const nextRatio = Math.min(
          MAX_CHAT_RATIO,
          Math.max(MIN_CHAT_RATIO, rawRatio),
        );
        setChatRatio(nextRatio);
      };
      const handlePointerMove = (moveEvent: PointerEvent): void => {
        updateRatio(moveEvent.clientX);
      };
      const handlePointerUp = (): void => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
      };
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp, { once: true });
    },
    [setChatRatio],
  );

  useEffect(() => {
    if (isLoadingMore && !isLoadingMoreRef.current) {
      const viewport = viewportRef.current;
      if (viewport) {
        savedScrollRef.current = captureChatScrollAnchor(
          viewport,
          visibleTimelineItem(viewport),
        );
      }
    }
    isLoadingMoreRef.current = isLoadingMore;
  }, [isLoadingMore]);

  useLayoutEffect(() => {
    if (previousSessionIdRef.current === sessionId) {
      return;
    }
    previousSessionIdRef.current = sessionId;
    isInitialScrollRef.current = true;
    isReadyForPaginationRef.current = false;
    isFollowingLatestRef.current = true;
    setShowNewMessageChip(false);
    prevMessageIdsRef.current = new Set();
    pendingInitialScrollRestoreRef.current = null;
    lastAutoLoadAttemptKeyRef.current = null;
    detachedScrollRestoreUntilRef.current = 0;

    if (sessionId === null) {
      return;
    }
    pendingInitialScrollRestoreRef.current = storedScrollState;
  }, [sessionId, storedScrollState]);
  useLayoutEffect(() => {
    const saved = savedScrollRef.current;
    const viewport = viewportRef.current;
    if (saved && viewport && !isLoadingMore) {
      const pendingDetachedScrollState = pendingInitialScrollRestoreRef.current;
      markProgrammaticScroll();
      if (
        pendingDetachedScrollState !== null &&
        !pendingDetachedScrollState.following
      ) {
        const maxDistanceFromBottom = Math.max(
          0,
          viewport.scrollHeight - viewport.clientHeight,
        );
        detachedScrollRestoreUntilRef.current =
          performance.now() + PROGRAMMATIC_SCROLL_GUARD_MS;
        viewport.scrollTop = Math.max(
          0,
          maxDistanceFromBottom - pendingDetachedScrollState.distanceFromBottom,
        );
        isFollowingLatestRef.current = false;
        if (
          !hasMore ||
          maxDistanceFromBottom >= pendingDetachedScrollState.distanceFromBottom
        ) {
          pendingInitialScrollRestoreRef.current = null;
        }
      } else {
        viewport.scrollTop = restorePrependScrollTop(saved, viewport);
      }
      savedScrollRef.current = null;
      prevMessageIdsRef.current = new Set(
        getTimelineItemIds(
          messages,
          pendingInputBuffers,
          liveRun,
          visibleActionExecutions,
        ),
      );
    }
  }, [
    messages,
    pendingInputBuffers,
    liveRun,
    visibleActionExecutions,
    hasMore,
    isLoadingMore,
    markProgrammaticScroll,
  ]);

  const loadOlderUntilViewportScrollable = useCallback((): void => {
    const viewport = viewportRef.current;
    if (
      viewport === null ||
      !isReadyForPaginationRef.current ||
      !hasMore ||
      isLoadingMore
    ) {
      return;
    }
    const pendingDetachedScrollState = pendingInitialScrollRestoreRef.current;
    const maxDistanceFromBottom = Math.max(
      0,
      viewport.scrollHeight - viewport.clientHeight,
    );
    const needsDetachedRestoreHistory =
      pendingDetachedScrollState !== null &&
      !pendingDetachedScrollState.following &&
      maxDistanceFromBottom < pendingDetachedScrollState.distanceFromBottom;
    if (
      viewport.scrollHeight > viewport.clientHeight &&
      !needsDetachedRestoreHistory
    ) {
      return;
    }
    const autoLoadAttemptKey = `${viewport.scrollHeight}:${viewport.clientHeight}:${contentRef.current?.scrollHeight ?? 0}`;
    if (lastAutoLoadAttemptKeyRef.current === autoLoadAttemptKey) {
      return;
    }
    lastAutoLoadAttemptKeyRef.current = autoLoadAttemptKey;
    savedScrollRef.current = captureChatScrollAnchor(
      viewport,
      visibleTimelineItem(viewport),
    );
    onLoadMore({
      detachFromLatest: !isFollowingLatestRef.current,
    });
  }, [hasMore, isLoadingMore, onLoadMore]);
  useLayoutEffect(() => {
    if (
      !isInitialScrollRef.current ||
      chatViewState.type !== "READY" ||
      savedScrollRef.current
    ) {
      return;
    }
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const storedScrollState = pendingInitialScrollRestoreRef.current;
    if (storedScrollState !== null && !storedScrollState.following) {
      const maxDistanceFromBottom = Math.max(
        0,
        viewport.scrollHeight - viewport.clientHeight,
      );
      markProgrammaticScroll();
      detachedScrollRestoreUntilRef.current =
        performance.now() + PROGRAMMATIC_SCROLL_GUARD_MS;
      viewport.scrollTop = Math.max(
        0,
        maxDistanceFromBottom - storedScrollState.distanceFromBottom,
      );
      isFollowingLatestRef.current = false;
      if (
        !hasMore ||
        maxDistanceFromBottom >= storedScrollState.distanceFromBottom
      ) {
        pendingInitialScrollRestoreRef.current = null;
      }
    } else {
      pendingInitialScrollRestoreRef.current = null;
      pinToBottom();
      isFollowingLatestRef.current = true;
    }
    isInitialScrollRef.current = false;
    prevMessageIdsRef.current = new Set(
      getTimelineItemIds(
        messages,
        pendingInputBuffers,
        liveRun,
        visibleActionExecutions,
      ),
    );
    requestAnimationFrame(() => {
      isReadyForPaginationRef.current = true;
      loadOlderUntilViewportScrollable();
    });
  }, [
    messages,
    pendingInputBuffers,
    liveRun,
    visibleActionExecutions,
    chatViewState.type,
    hasMore,
    loadOlderUntilViewportScrollable,
    markProgrammaticScroll,
    pinToBottom,
  ]);

  useEffect(() => {
    const frame = requestAnimationFrame(loadOlderUntilViewportScrollable);
    return () => cancelAnimationFrame(frame);
  }, [
    visibleActionExecutions,
    loadOlderUntilViewportScrollable,
    messages,
    pendingInputBuffers,
  ]);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) {
      return;
    }
    const ro = new ResizeObserver(() => {
      if (isFollowingLatestRef.current) {
        schedulePinToBottom();
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [schedulePinToBottom]);

  useEffect(() => {
    const visualViewport = window.visualViewport;
    if (!visualViewport) {
      return;
    }
    const handleViewportChange = (): void => {
      if (isFollowingLatestRef.current) {
        schedulePinToBottom();
      }
    };
    visualViewport.addEventListener("resize", handleViewportChange);
    visualViewport.addEventListener("scroll", handleViewportChange);
    return () => {
      visualViewport.removeEventListener("resize", handleViewportChange);
      visualViewport.removeEventListener("scroll", handleViewportChange);
    };
  }, [schedulePinToBottom]);
  useEffect(() => {
    if (chatViewState.type === "LOADING_HISTORY" && !hasTimelineItems) {
      isInitialScrollRef.current = true;
      isReadyForPaginationRef.current = false;
      isFollowingLatestRef.current = true;
      setShowNewMessageChip(false);
      prevMessageIdsRef.current = new Set();
    }
  }, [chatViewState.type, hasTimelineItems]);
  useEffect(() => {
    if (isInitialScrollRef.current || savedScrollRef.current) {
      return;
    }

    const prevIds = prevMessageIdsRef.current;
    const timelineItemIds = getTimelineItemIds(
      messages,
      pendingInputBuffers,
      liveRun,
      visibleActionExecutions,
    );
    const hasNewMessage = timelineItemIds.some((id) => !prevIds.has(id));
    prevMessageIdsRef.current = new Set(timelineItemIds);
    if (!hasNewMessage) {
      if (isFollowingLatestRef.current) {
        schedulePinToBottom();
      }
      return;
    }
    if (isFollowingLatestRef.current) {
      schedulePinToBottom();
    } else {
      setShowNewMessageChip(true);
    }
  }, [
    messages,
    pendingInputBuffers,
    liveRun,
    visibleActionExecutions,
    schedulePinToBottom,
  ]);
  useEffect(() => {
    const viewport = viewportRef.current;
    const scrollArea = scrollAreaRef.current;
    if (!viewport || !scrollArea) {
      return;
    }

    const handleScroll = (): void => {
      const scrollTop = viewport.scrollTop;

      if (isLoadingMore && savedScrollRef.current !== null) {
        savedScrollRef.current = captureChatScrollAnchor(
          viewport,
          visibleTimelineItem(viewport),
        );
      }
      const distanceFromBottom = scrollDistanceFromBottom(viewport);
      const atFollowBoundary = distanceFromBottom <= BOTTOM_FOLLOW_THRESHOLD;
      const now = performance.now();
      const inProgrammaticScroll = now < programmaticScrollUntilRef.current;
      const pendingDetachedScrollState = pendingInitialScrollRestoreRef.current;
      const isRestoringDetachedScroll =
        (pendingDetachedScrollState !== null &&
          !pendingDetachedScrollState.following) ||
        now < detachedScrollRestoreUntilRef.current;
      if (isRestoringDetachedScroll) {
        isFollowingLatestRef.current = false;
      } else if (atFollowBoundary) {
        isFollowingLatestRef.current = true;
      } else if (!inProgrammaticScroll) {
        isFollowingLatestRef.current = false;
      }
      if (!isRestoringDetachedScroll) {
        persistScrollState(viewport, isFollowingLatestRef.current);
      }
      if (atFollowBoundary && !isRestoringDetachedScroll) {
        setShowNewMessageChip(false);
        if (
          chatTimelineState.type === "DETACHED_HISTORY_BROWSING" &&
          isReadyForPaginationRef.current &&
          !isLoadingNewer
        ) {
          if (hasDetachedNewer) {
            onLoadNewer();
          } else {
            onResetToLatest();
          }
        }
      }
      if (
        scrollTop <= LOAD_MORE_THRESHOLD &&
        hasMore &&
        !isLoadingMore &&
        isReadyForPaginationRef.current &&
        !inProgrammaticScroll
      ) {
        const lastLoadMoreTriggerAt = lastLoadMoreTriggerAtRef.current;
        if (now - lastLoadMoreTriggerAt >= LOAD_MORE_COOLDOWN_MS) {
          lastLoadMoreTriggerAtRef.current = now;
          savedScrollRef.current = captureChatScrollAnchor(
            viewport,
            visibleTimelineItem(viewport),
          );
          onLoadMore();
        }
      }
    };

    viewport.addEventListener("wheel", markUserScrollIntent, { passive: true });
    viewport.addEventListener("touchstart", markUserScrollIntent, {
      passive: true,
    });
    viewport.addEventListener("touchmove", markUserScrollIntent, {
      passive: true,
    });
    scrollArea.addEventListener("pointerdown", markUserScrollIntent, {
      passive: true,
    });
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      viewport.removeEventListener("wheel", markUserScrollIntent);
      viewport.removeEventListener("touchstart", markUserScrollIntent);
      viewport.removeEventListener("touchmove", markUserScrollIntent);
      scrollArea.removeEventListener("pointerdown", markUserScrollIntent);
      viewport.removeEventListener("scroll", handleScroll);
    };
  }, [
    chatTimelineState.type,
    hasDetachedNewer,
    isMobile,
    hasMore,
    isLoadingMore,
    isLoadingNewer,
    markUserScrollIntent,
    onLoadMore,
    onLoadNewer,
    onResetToLatest,
    persistScrollState,
  ]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (
        event.key === "ArrowUp" ||
        event.key === "ArrowDown" ||
        event.key === "PageUp" ||
        event.key === "PageDown" ||
        event.key === "Home" ||
        event.key === "End" ||
        event.key === " "
      ) {
        markUserScrollIntent();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [markUserScrollIntent]);
  const scrollToBottom = useCallback(() => {
    setShowNewMessageChip(false);
    isFollowingLatestRef.current = true;
    if (chatTimelineState.type === "DETACHED_HISTORY_BROWSING") {
      onResetToLatest();
      return;
    }
    if (viewportRef.current) {
      markProgrammaticScroll();
      viewportRef.current.scrollTo({
        top: viewportRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [chatTimelineState.type, markProgrammaticScroll, onResetToLatest]);

  const scrollToBottomImmediately = useCallback(() => {
    setShowNewMessageChip(false);
    isFollowingLatestRef.current = true;
    pinToBottom();
  }, [pinToBottom]);

  const handleInputFocus = useCallback(() => {
    if (!isMobile || !isFollowingLatestRef.current) {
      return;
    }
    requestAnimationFrame(scrollToBottomImmediately);
    window.setTimeout(scrollToBottomImmediately, KEYBOARD_RESIZE_SETTLE_MS);
  }, [isMobile, scrollToBottomImmediately]);
  const handleAfterSend = useCallback(() => {
    setShowNewMessageChip(false);
    isFollowingLatestRef.current = true;
    schedulePinToBottom();
  }, [schedulePinToBottom]);

  return {
    chatViewState,
    chatTimelineState,
    messages,
    timelineEvents,
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
    onSendInput,
    onDeletePendingInputBuffer,
    onClearGoal,
    onUpdateGoal,
    onPauseGoal,
    onResumeGoal,
    hasMore,
    isLoadingMore,
    isLoadingNewer,
    onLoadMore,
    onLoadNewer,
    onResetToLatest,
    onSubmitMessageEdit,
    onRetryFailedRun,
    wasCommandBlocked,
    isStopAvailable,
    isStopPending,
    onStopRequest,
    inputActions,
    authorizationRequests,
    onAuthorizationComplete,
    actionExecutions,
    workspacePanel,
    goal,
    todo,
    currentWorkspaceProfile,
    readOnlyNotice,
    t,
    scrollAreaRef,
    viewportRef,
    contentRef,
    splitContainerRef,
    pendingFiles,
    addFiles,
    removeFile,
    clearFiles,
    resetDoneFiles,
    uploadAll,
    isUploading,
    showNewMessageChip,
    chatRatio,
    editingMessage,
    isMobile,
    latestCompactionIndex,
    completedCompactionIdSet,
    hasDetachedNewer,
    latestVisibleId,
    latestActivityId,
    liveRetryRun,
    liveOperationRun,
    activeRun,
    visibleActionExecutions,
    actionExecutionPlacement,
    chatPresentationItems,
    activeActivitySource,
    activeActivity,
    attachedAuthorizationRequest,
    unattachedAuthorizationRequests,
    hasTimelineItems,
    editingMessageIndex,
    handleStartEdit,
    handleCancelEdit,
    handleSubmitInput,
    handleWorkspaceResizeStart,
    scrollToBottom,
    handleInputFocus,
    handleAfterSend,
  };
}
