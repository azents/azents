"use client";

/**
 * chat view component.
 *
 * message list, streaming indicator, input area includes..
 *
 * Scroll policy:
 * - initial load: useLayoutEffect with scroll to bottom before paint (prevent flicker/misfire)
 *   → enable pagination after scroll stabilizes (isReadyForPaginationRef)
 * - follow active: within the 48px bottom/iOS bounce boundary, new output stays pinned
 * - follow stop: explicit user scroll beyond that same boundary shows the new-message control
 * - when user sends message: always bottom with scroll
 * - scrolling up loads older messages (pagination), preserve scroll position.
 */

import {
  Badge,
  Box,
  Center,
  Group,
  Loader,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconArrowDown,
  IconGripVertical,
  IconMessageOff,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import {
  Fragment,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { type UploadedFile, useFileUpload } from "../hooks/useFileUpload";
import { projectChatPresentationItems } from "../toolActivityPresentation";
import { WorkspacePanel } from "../workspace/components/WorkspacePanel";
import { ActionExecutionTimelineCard } from "./ActionExecutionTimelineCard";
import { AgentRunIndicator } from "./AgentRunIndicator";
import { AuthorizationRequestBubble } from "./AuthorizationRequestBubble";
import { ChatInput } from "./ChatInput";
import { CompactionDivider } from "./CompactionDivider";
import { CompactionIndicator } from "./CompactionIndicator";
import { MessageBubble } from "./MessageBubble";
import { OptimisticInputBubble } from "./OptimisticInputBubble";
import { PendingInputBufferBubble } from "./PendingInputBufferBubble";
import { RunRetryCard } from "./RunRetryCard";
import { ToolActivityGroup } from "./ToolActivityGroup";
import { TurnDivider } from "./TurnDivider";
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

/** older messages load trigger scroll position (px) */
const LOAD_MORE_THRESHOLD = 100;
/** tail follow detection allowed distance (px). mobile viewport/sub-pixel/keyboard resize absorbs error.. */
const BOTTOM_FOLLOW_THRESHOLD = 48;
const PROGRAMMATIC_SCROLL_GUARD_MS = 350;
const LOAD_MORE_COOLDOWN_MS = 800;
const CHAT_SCROLL_STATE_STORAGE_PREFIX = "azents.chat.scrollState.";
const NEW_MESSAGE_CHIP_OFFSET = "calc(100% + var(--mantine-spacing-xl))";
const KEYBOARD_RESIZE_SETTLE_MS = 250;
const WORKSPACE_RATIO_STORAGE_KEY = "azents.chat.workspaceRatio";
const DEFAULT_CHAT_RATIO = 0.55;
const MIN_CHAT_RATIO = 0.35;
const MAX_CHAT_RATIO = 0.75;

/** viewport bottom or iOS bounce area to existstext determines.. */
function scrollDistanceFromBottom(viewport: HTMLDivElement): number {
  const { scrollTop, scrollHeight, clientHeight } = viewport;
  return Math.max(0, scrollHeight - scrollTop - clientHeight);
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
    if (typeof parsed !== "object" || parsed === null) {
      return null;
    }
    const record = parsed as Record<string, unknown>;
    if (
      typeof record.distanceFromBottom === "number" &&
      typeof record.following === "boolean"
    ) {
      return {
        distanceFromBottom: record.distanceFromBottom,
        following: record.following,
      };
    }
  } catch {
    return null;
  }
  return null;
}

interface BoundaryControls {
  usage: Record<string, unknown> | null;
}

interface EditingMessageState {
  messageId: string;
  content: string;
  inferenceProfile: RequestedInferenceProfile | null;
}

/** message row with directly not rendered as completion markerwhether checks.. */
function isBoundaryMessage(message: ChatMessage): boolean {
  return message.role === "turn_complete" || message.role === "run_complete";
}

/** aftertext completion marker can attach actual display messagewhether checks.. */
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

/** latest compaction summary position returns.. */
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

interface ActionExecutionTimelinePlacement {
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

/** Build scroll-tracking IDs in the same order as rendered timeline items. */
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

/** display message bar with after to text completion marker UI control with collects.. */
function getBoundaryControls(
  messages: ChatMessage[],
  messageIndex: number,
): BoundaryControls {
  let usage: Record<string, unknown> | null = null;

  for (let i = messageIndex + 1; i < messages.length; i += 1) {
    const next = messages[i];
    if (!next) {
      continue;
    }
    if (isVisibleMessageAnchor(next) || next.role === "compaction") {
      break;
    }
    if (next.role === "turn_complete") {
      usage = next.usage ?? null;
      continue;
    }
  }

  return { usage };
}

interface ChatViewProps {
  chatViewState: ChatViewState;
  chatTimelineState: ChatTimelineState;
  messages: ChatMessage[];
  /** canonical durable and latest-following live event stream */
  timelineEvents: ChatEventResponse[];
  /** not yet model turn  to not injected pending input buffers */
  pendingInputBuffers: PendingInputBuffer[];
  activeAgent: AgentResponse | null;
  defaultInferenceProfile: RequestedInferenceProfile;
  sessionId?: string | null;
  isResponsePending: boolean;
  isWritePending: boolean;
  isModelResponsePending: boolean;
  /** current live run snapshot with retry recovery state */
  liveRun: ChatLiveRunState | null;
  /** latest context-window usage snapshot */
  tokenUsage?: TokenUsageSummary | null;
  /** notifies the session header when the composer profile changes */
  onComposerInferenceProfileChange?: (
    profile: RequestedInferenceProfile,
  ) => void;
  onSendInput: (
    message: string,
    action: ChatAction | null,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** delete pending input buffer */
  onDeletePendingInputBuffer: (bufferId: string) => void;
  /** Goal delete */
  onClearGoal: () => Promise<boolean>;
  /** Goal update */
  onUpdateGoal: (objective: string) => Promise<boolean>;
  /** Goal textwhentext */
  onPauseGoal: () => Promise<boolean>;
  /** Goal text */
  onResumeGoal: (hint?: string) => Promise<boolean>;
  /** whether older messages exist */
  hasMore: boolean;
  /** older messages loading */
  isLoadingMore: boolean;
  /** newer messages loading */
  isLoadingNewer: boolean;
  /** load older events; automatic viewport filling keeps latest-follow state */
  onLoadMore: (options?: { detachFromLatest?: boolean }) => void;
  /** newer messages  withtext */
  onLoadNewer: () => void;
  /** latest reset */
  onResetToLatest: () => void;
  /** submit user message edit */
  onSubmitMessageEdit: (
    messageId: string,
    message: string,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** retry the latest terminal failed run */
  onRetryFailedRun: (failedEventId: string) => Promise<boolean>;
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
  /** pending OAuth authorization request list */
  authorizationRequests: AuthorizationRequest[];
  /** auth complete when remove corresponding request */
  onAuthorizationComplete: (toolkitId: string) => void;
  /** current operation TurnAction execution projections */
  actionExecutions: ActionExecutionProjection[];
  /** Workspace panel container output */
  workspacePanel: WorkspacePanelContainerOutput;
  /** current session goal snapshot */
  goal: GoalStateSnapshot;
  /** current session todo snapshot */
  todo: TodoStateSnapshot;
  /** read-only notice shown instead of the composer */
  readOnlyNotice?: string | null;
}

export function ChatView({
  chatViewState,
  chatTimelineState,
  messages,
  timelineEvents,
  pendingInputBuffers,
  activeAgent,
  defaultInferenceProfile,
  sessionId = null,
  isResponsePending,
  isWritePending,
  isModelResponsePending,
  liveRun,
  tokenUsage = null,
  onComposerInferenceProfileChange,
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
  readOnlyNotice = null,
}: ChatViewProps): React.ReactElement {
  const t = useTranslations("chat");
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const isInitialScrollRef = useRef(true);
  // file upload
  const {
    pendingFiles,
    addFiles,
    removeFile,
    clearFiles,
    resetDoneFiles,
    uploadAll,
    isUploading,
  } = useFileUpload();

  // new timeline item/streaming update bottom with according totext whether.
  // bottom or iOS bottom bounce area inonly true text, textwhen immediately false text.
  const isFollowingLatestRef = useRef(true);
  // new message when arrives show chip whether
  const [showNewMessageChip, setShowNewMessageChip] = useState(false);
  // previous message ID text (new message textfor)
  const prevMessageIdsRef = useRef<Set<string>>(new Set());
  // flag to enable pagination after initial scroll completes
  const isReadyForPaginationRef = useRef(false);

  const [chatRatio, setChatRatio] = useState(DEFAULT_CHAT_RATIO);
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

  // whether mobile determine (touch device)
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
  const latestActivityId = useMemo(() => {
    for (let index = chatPresentationItems.length - 1; index >= 0; index -= 1) {
      const item = chatPresentationItems[index];
      if (item?.type === "activity") {
        return item.id;
      }
    }
    return null;
  }, [chatPresentationItems]);
  const attachedAuthorizationRequest =
    latestActivityId === null ? null : (authorizationRequests[0] ?? null);
  const unattachedAuthorizationRequests =
    attachedAuthorizationRequest === null
      ? authorizationRequests
      : authorizationRequests.slice(1);
  const hasTimelineItems =
    messages.length > 0 ||
    pendingInputBuffers.length > 0 ||
    liveRetryVisible ||
    liveOperationVisible ||
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

  // older messages prepend when preserve scroll position
  const isLoadingMoreRef = useRef(false);
  const lastAutoLoadAttemptKeyRef = useRef<string | null>(null);
  const savedScrollRef = useRef<{
    scrollHeight: number;
    scrollTop: number;
  } | null>(null);

  const markProgrammaticScroll = useCallback((): void => {
    programmaticScrollUntilRef.current =
      performance.now() + PROGRAMMATIC_SCROLL_GUARD_MS;
  }, []);

  const markUserScrollIntent = useCallback((): void => {
    programmaticScrollUntilRef.current = 0;
    detachedScrollRestoreUntilRef.current = 0;
    userScrollIntentGenerationRef.current += 1;
    pendingInitialScrollRestoreRef.current = null;
    savedScrollRef.current = null;
  }, []);

  const persistScrollState = useCallback(
    (viewport: HTMLDivElement, following: boolean): void => {
      if (sessionId === null || typeof window === "undefined") {
        return;
      }
      try {
        window.sessionStorage.setItem(
          `${CHAT_SCROLL_STATE_STORAGE_PREFIX}${sessionId}`,
          JSON.stringify({
            distanceFromBottom: scrollDistanceFromBottom(viewport),
            following,
          } satisfies StoredChatScrollState),
        );
      } catch {
        // Ignore storage failures (private mode/quota) and keep in-memory behavior.
      }
    },
    [sessionId],
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

  useEffect(() => {
    const stored = window.localStorage.getItem(WORKSPACE_RATIO_STORAGE_KEY);
    if (stored === null) {
      return;
    }
    const parsed = Number.parseFloat(stored);
    if (!Number.isFinite(parsed)) {
      return;
    }
    setChatRatio(Math.min(MAX_CHAT_RATIO, Math.max(MIN_CHAT_RATIO, parsed)));
  }, []);

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
        window.localStorage.setItem(
          WORKSPACE_RATIO_STORAGE_KEY,
          nextRatio.toString(),
        );
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
    [],
  );

  useEffect(() => {
    // isLoadingMore true with switchtext when current scroll position save
    if (isLoadingMore && !isLoadingMoreRef.current) {
      const viewport = viewportRef.current;
      if (viewport) {
        savedScrollRef.current = {
          scrollHeight: viewport.scrollHeight,
          scrollTop: viewport.scrollTop,
        };
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

    if (sessionId === null || typeof window === "undefined") {
      return;
    }
    try {
      pendingInitialScrollRestoreRef.current = parseStoredChatScrollState(
        window.sessionStorage.getItem(
          `${CHAT_SCROLL_STATE_STORAGE_PREFIX}${sessionId}`,
        ),
      );
    } catch {
      pendingInitialScrollRestoreRef.current = null;
    }
  }, [sessionId]);

  // older messages prepend after scroll position restore
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
        const diff = viewport.scrollHeight - saved.scrollHeight;
        viewport.scrollTop = saved.scrollTop + diff;
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
    savedScrollRef.current = {
      scrollHeight: viewport.scrollHeight,
      scrollTop: viewport.scrollTop,
    };
    onLoadMore({
      detachFromLatest: !isFollowingLatestRef.current,
    });
  }, [hasMore, isLoadingMore, onLoadMore]);

  // initial load when paint before to bottom with scroll.
  // useEffect(paint after) itext useLayoutEffect(paint before) in handledtext
  // scrollTop=0 status in scroll event onLoadMore misfire text prevention.
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

    // text after next frame pagination enable (sectext scroll insidetext waiting)
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

  // First history load resets scroll; same-session reloads keep the current follow state.
  useEffect(() => {
    if (chatViewState.type === "LOADING_HISTORY" && !hasTimelineItems) {
      isInitialScrollRef.current = true;
      isReadyForPaginationRef.current = false;
      isFollowingLatestRef.current = true;
      setShowNewMessageChip(false);
      prevMessageIdsRef.current = new Set();
    }
  }, [chatViewState.type, hasTimelineItems]);

  // message/pending buffer change when conditional scroll (initial load except — useLayoutEffect in handle)
  // - new timeline item + follow active: smooth scroll
  // - new timeline item + follow stop: show chip (scroll inside do)
  // - streaming update (text ID): follow activewhenonly instant scroll
  // - initial load / pagination during: text (eacheach useLayoutEffect in handle)
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

    // snapshot update
    prevMessageIdsRef.current = new Set(timelineItemIds);

    // streaming text update (existing message content change): bottomwhen follow
    if (!hasNewMessage) {
      if (isFollowingLatestRef.current) {
        schedulePinToBottom();
      }
      return;
    }

    // new message arrival
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

  // integration scroll handler: bottom detection + new message chip release + older messages  withtext + mobile header hide/display
  useEffect(() => {
    const viewport = viewportRef.current;
    const scrollArea = scrollAreaRef.current;
    if (!viewport || !scrollArea) {
      return;
    }

    const handleScroll = (): void => {
      const scrollTop = viewport.scrollTop;

      // (1) follow detection update
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

      // bottom or bottom bounce area to alsotextwhen new message chip hide.
      // text bottom in text textonly with detached/buffering switchdoes not..
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

      // (2) older messages load trigger (sectext scroll insidetext after toonly enable)
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
          savedScrollRef.current = {
            scrollHeight: viewport.scrollHeight,
            scrollTop: viewport.scrollTop,
          };
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

  /** bottom with scroll + chip hide */
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

  /** message send after scroll handle callback (ChatInput in call) */
  const handleAfterSend = useCallback(() => {
    setShowNewMessageChip(false);
    isFollowingLatestRef.current = true;
    schedulePinToBottom();
  }, [schedulePinToBottom]);

  // empty status
  if (chatViewState.type === "EMPTY") {
    return (
      <Center h="100%">
        <Stack align="center" gap="md">
          <IconMessageOff size={48} color="var(--mantine-color-dimmed)" />
          <Text c="dimmed" ta="center" style={{ whiteSpace: "pre-line" }}>
            {t("selectAgent")}
          </Text>
        </Stack>
      </Center>
    );
  }

  // history loading
  if (chatViewState.type === "LOADING_HISTORY" && !hasTimelineItems) {
    return (
      <Center h="100%">
        <Stack align="center" gap="md">
          <Loader size="lg" />
          <Text c="dimmed">{t("loadingHistory")}</Text>
        </Stack>
      </Center>
    );
  }

  // chat view
  return (
    <Group
      ref={splitContainerRef}
      h="100%"
      mih={0}
      w="100%"
      gap={0}
      align="stretch"
      wrap="nowrap"
      style={{ overflow: "hidden" }}
    >
      <Stack
        h="100%"
        mih={0}
        miw={0}
        flex={1}
        gap={0}
        style={{
          position: "relative",
          overflow: "hidden",
          flexBasis: `${chatRatio * 100}%`,
        }}
      >
        {/* message area */}
        <ScrollArea
          flex={1}
          mih={0}
          ref={scrollAreaRef}
          viewportRef={viewportRef}
          styles={{ root: { minWidth: 0 }, viewport: { minWidth: 0 } }}
        >
          <Box
            ref={contentRef}
            px="md"
            pb="md"
            maw={rem(920)}
            mx="auto"
            w="100%"
            pt="md"
          >
            {/* older messages loading indicator */}
            {isLoadingMore && (
              <Center py="sm">
                <Loader size="sm" />
              </Center>
            )}
            {!hasTimelineItems && !isResponsePending ? (
              <Center py="xl">
                <Text c="dimmed" size="sm">
                  {t("startConversation")}
                </Text>
              </Center>
            ) : (
              <Stack gap={0}>
                {chatPresentationItems.map((item) => {
                  if (item.type === "activity") {
                    const durableBefore =
                      actionExecutionPlacement.durableBeforeMessage.get(
                        item.activity.firstMessageId,
                      ) ?? [];
                    const dimmedByEdit =
                      editingMessageIndex !== null &&
                      item.activity.endMessageIndex >= editingMessageIndex;
                    return (
                      <Fragment key={item.id}>
                        {durableBefore.map((actionExecution) => (
                          <ActionExecutionTimelineCard
                            key={actionExecution.execution.id}
                            actionExecution={actionExecution}
                          />
                        ))}
                        <ToolActivityGroup
                          activity={item.activity}
                          dimmed={dimmedByEdit}
                          authorizationAction={
                            item.id === latestActivityId &&
                            attachedAuthorizationRequest !== null ? (
                              <AuthorizationRequestBubble
                                variant="compact"
                                toolkitName={
                                  attachedAuthorizationRequest.toolkitName
                                }
                                authorizationUrl={
                                  attachedAuthorizationRequest.authorizationUrl
                                }
                                onAuthorized={() =>
                                  onAuthorizationComplete(
                                    attachedAuthorizationRequest.toolkitId,
                                  )
                                }
                              />
                            ) : null
                          }
                        />
                        <TurnDivider usage={item.activity.usage} />
                      </Fragment>
                    );
                  }

                  const msg = item.message;
                  const index = item.messageIndex;
                  const durableBefore =
                    actionExecutionPlacement.durableBeforeMessage.get(msg.id) ??
                    [];
                  if (msg.role === "compaction") {
                    return (
                      <Fragment key={item.id}>
                        {durableBefore.map((actionExecution) => (
                          <ActionExecutionTimelineCard
                            key={actionExecution.execution.id}
                            actionExecution={actionExecution}
                          />
                        ))}
                        <CompactionDivider content={msg.content} />
                      </Fragment>
                    );
                  }
                  if (
                    msg.role === "compaction_started" ||
                    isBoundaryMessage(msg)
                  ) {
                    return durableBefore.length > 0 ? (
                      <Fragment key={item.id}>
                        {durableBefore.map((actionExecution) => (
                          <ActionExecutionTimelineCard
                            key={actionExecution.execution.id}
                            actionExecution={actionExecution}
                          />
                        ))}
                      </Fragment>
                    ) : null;
                  }
                  const boundaryControls = getBoundaryControls(messages, index);
                  const dimmedByEdit =
                    editingMessageIndex !== null &&
                    index >= editingMessageIndex;
                  const editableUserMessage =
                    readOnlyNotice === null &&
                    msg.role === "user" &&
                    Boolean(msg.content) &&
                    msg.status !== "partial" &&
                    index > latestCompactionIndex &&
                    !isResponsePending;
                  const failedRunRetryAction = msg.failedRunFailure
                    ? {
                        canRetry:
                          chatTimelineState.type === "LATEST_FOLLOWING" &&
                          msg.id === latestVisibleId &&
                          !isResponsePending &&
                          !isWritePending &&
                          !isStopAvailable &&
                          pendingInputBuffers.length === 0,
                        isPending: isWritePending,
                        onRetry: () => {
                          void onRetryFailedRun(msg.id);
                        },
                      }
                    : null;
                  return (
                    <Fragment key={item.id}>
                      {durableBefore.map((actionExecution) => (
                        <ActionExecutionTimelineCard
                          key={actionExecution.execution.id}
                          actionExecution={actionExecution}
                        />
                      ))}
                      <MessageBubble
                        message={msg}
                        dimmed={dimmedByEdit}
                        editable={editableUserMessage}
                        onEdit={() => handleStartEdit(msg)}
                        failedRunRetryAction={failedRunRetryAction}
                      />
                      <TurnDivider usage={boundaryControls.usage} />
                    </Fragment>
                  );
                })}
                {actionExecutionPlacement.durableTail.map((actionExecution) => (
                  <ActionExecutionTimelineCard
                    key={actionExecution.execution.id}
                    actionExecution={actionExecution}
                  />
                ))}
                {unattachedAuthorizationRequests.map((req) => (
                  <AuthorizationRequestBubble
                    key={req.toolkitId}
                    toolkitName={req.toolkitName}
                    authorizationUrl={req.authorizationUrl}
                    onAuthorized={() => onAuthorizationComplete(req.toolkitId)}
                  />
                ))}
                {liveRetryRun !== null && (
                  <RunRetryCard
                    variant="live"
                    retry={liveRetryRun.retry}
                    phase={liveRetryRun.phase}
                  />
                )}
                {liveOperationRun !== null && <CompactionIndicator />}
                {chatTimelineState.type === "LATEST_FOLLOWING" &&
                  !liveRetryVisible &&
                  !liveOperationVisible &&
                  isModelResponsePending && (
                    <AgentRunIndicator
                      modelCallStartedAt={liveRun?.modelCallStartedAt ?? null}
                    />
                  )}
                {actionExecutionPlacement.liveTail.map((actionExecution) => (
                  <ActionExecutionTimelineCard
                    key={actionExecution.execution.id}
                    actionExecution={actionExecution}
                  />
                ))}
                {chatTimelineState.type === "LATEST_FOLLOWING" &&
                  pendingInputBuffers.map((buffer) =>
                    buffer.id.startsWith("optimistic:") ? (
                      <OptimisticInputBubble key={buffer.id} buffer={buffer} />
                    ) : (
                      <PendingInputBufferBubble
                        key={buffer.id}
                        buffer={buffer}
                        onDelete={onDeletePendingInputBuffer}
                      />
                    ),
                  )}
              </Stack>
            )}
          </Box>
        </ScrollArea>

        <Box style={{ position: "relative", flexShrink: 0 }}>
          {/* new message notice chip */}
          {(showNewMessageChip || hasDetachedNewer) && (
            <Box
              style={{
                position: "absolute",
                bottom: NEW_MESSAGE_CHIP_OFFSET,
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: 2,
                pointerEvents: "auto",
              }}
            >
              <Badge
                component="button"
                type="button"
                size="lg"
                variant="filled"
                color="blue"
                rightSection={<IconArrowDown size={14} />}
                onClick={scrollToBottom}
                aria-label={t("newMessage")}
                style={{
                  cursor: "pointer",
                  boxShadow: "var(--mantine-shadow-md)",
                }}
              >
                {t("newMessage")}
              </Badge>
            </Box>
          )}
          {/* input area */}
          <Box px="md" py="sm">
            <Box maw={rem(920)} mx="auto">
              <ChatInput
                agentId={activeAgent?.id ?? null}
                sessionId={sessionId}
                isMobile={isMobile}
                selectableModelOptions={
                  activeAgent?.selectable_model_options ?? []
                }
                defaultInferenceProfile={defaultInferenceProfile}
                editingInferenceProfile={
                  editingMessage?.inferenceProfile ?? null
                }
                inferenceProfileSelectionEnabled={readOnlyNotice === null}
                contextUsageEnabled={sessionId !== null}
                contextUsage={tokenUsage}
                contextUsageActiveRun={liveRun}
                onInferenceProfileChange={onComposerInferenceProfileChange}
                isUploading={isUploading || isWritePending}
                pendingFiles={readOnlyNotice === null ? pendingFiles : []}
                goal={
                  readOnlyNotice === null && editingMessage === null
                    ? goal
                    : null
                }
                todo={
                  readOnlyNotice === null && editingMessage === null
                    ? todo
                    : null
                }
                onClearGoal={onClearGoal}
                onUpdateGoal={onUpdateGoal}
                onPauseGoal={onPauseGoal}
                onResumeGoal={onResumeGoal}
                uploadAll={uploadAll}
                onSendInput={handleSubmitInput}
                clearFiles={clearFiles}
                resetDoneFiles={resetDoneFiles}
                addFiles={addFiles}
                removeFile={removeFile}
                onAfterSend={handleAfterSend}
                onFocus={handleInputFocus}
                wasCommandBlocked={readOnlyNotice === null && wasCommandBlocked}
                isStopAvailable={isStopAvailable}
                isStopPending={isStopPending}
                onStopRequest={onStopRequest}
                inputActions={readOnlyNotice === null ? inputActions : []}
                editingMessageId={
                  readOnlyNotice === null
                    ? (editingMessage?.messageId ?? null)
                    : null
                }
                editingInitialValue={
                  readOnlyNotice === null
                    ? (editingMessage?.content ?? null)
                    : null
                }
                onCancelEdit={handleCancelEdit}
                editSendDisabled={editingMessage !== null && isResponsePending}
                inputDisabled={readOnlyNotice !== null}
                disabledPlaceholder={readOnlyNotice}
              />
            </Box>
          </Box>
        </Box>
      </Stack>
      <Box
        visibleFrom="lg"
        role="separator"
        aria-orientation="vertical"
        onPointerDown={handleWorkspaceResizeStart}
        h="100%"
        w={rem(10)}
        style={{
          cursor: "col-resize",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderLeft: `${rem(1)} solid var(--mantine-color-default-border)`,
        }}
      >
        <IconGripVertical size="1rem" color="var(--mantine-color-dimmed)" />
      </Box>
      <Box
        visibleFrom="lg"
        h="100%"
        style={{
          flex: `0 0 ${(1 - chatRatio) * 100}%`,
          minWidth: rem(320),
        }}
      >
        <WorkspacePanel {...workspacePanel} />
      </Box>
    </Group>
  );
}
