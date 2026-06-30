"use client";

/**
 * chat view component.
 *
 * message list, streaming indicator, input area includes..
 *
 * Scroll policy:
 * - initial load: useLayoutEffect with scroll to bottom before paint (prevent flicker/misfire)
 *   → enable pagination after scroll stabilizes (isReadyForPaginationRef)
 * - follow active: bottom or iOS bottom bounce area inonly new message/streaming auto-scroll
 * - follow stop: bottom/bounce area as soon as leaving stop and new timeline item when arrives "new message" show chip
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
import { WorkspacePanel } from "../workspace/components/WorkspacePanel";
import { AgentRunIndicator } from "./AgentRunIndicator";
import { AuthorizationRequestBubble } from "./AuthorizationRequestBubble";
import { ChatInput } from "./ChatInput";
import { CompactionDivider } from "./CompactionDivider";
import { CompactionIndicator } from "./CompactionIndicator";
import { MessageBubble } from "./MessageBubble";
import { OptimisticInputBubble } from "./OptimisticInputBubble";
import { PendingInputBufferBubble } from "./PendingInputBufferBubble";
import { SubagentBlock } from "./SubagentBlock";
import { SubagentDetailModal } from "./SubagentDetailModal";
import { TurnDivider } from "./TurnDivider";
import type {
  AuthorizationRequest,
  ChatAction,
  ChatMessage,
  ChatTimelineState,
  ChatViewState,
  GoalStateSnapshot,
  InputActionDefinition,
  PendingInputBuffer,
  TodoStateSnapshot,
} from "../types";
import type { WorkspacePanelContainerOutput } from "../workspace/containers/useWorkspacePanelContainer";
import type { AgentResponse } from "@azents/public-client";

/** older messages load trigger scroll position (px) */
const LOAD_MORE_THRESHOLD = 100;
/** tail follow detection allowed distance (px). mobile viewport/sub-pixel/keyboard resize absorbs error.. */
const BOTTOM_FOLLOW_THRESHOLD = 48;
const PROGRAMMATIC_SCROLL_GUARD_MS = 350;
const LOAD_MORE_COOLDOWN_MS = 800;
/** distance that intentionally exits latest-follow mode (roughly a paragraph or two). */
const FOLLOW_EXIT_THRESHOLD = 160;
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
}

/** message row with directly not rendered as completion markerwhether checks.. */
function isBoundaryMessage(message: ChatMessage): boolean {
  return message.role === "turn_complete" || message.role === "run_complete";
}

/** un partial text/tool running display existstextwhen peralso run indicator hides.. */
function shouldShowPendingIndicator(messages: ChatMessage[]): boolean {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const previous = messages[i];
    if (!previous) {
      continue;
    }
    if (previous.role === "user" || isBoundaryMessage(previous)) {
      break;
    }
    if (previous.role !== "assistant") {
      continue;
    }
    if (previous.status === "partial") {
      return false;
    }
    if (previous.toolCalls?.some((toolCall) => toolCall.status === "running")) {
      return false;
    }
  }

  return true;
}

/** aftertext completion marker can attach actual display messagewhether checks.. */
function isVisibleMessageAnchor(message: ChatMessage): boolean {
  return (
    !isBoundaryMessage(message) &&
    message.role !== "compaction_started" &&
    message.role !== "subagent_end" &&
    message.role !== "compaction"
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

/** scroll textfor with durable message and pending buffer  text of timeline  with combines.. */
function getTimelineItemIds(
  messages: ChatMessage[],
  pendingInputBuffers: PendingInputBuffer[],
): string[] {
  return [
    ...messages.map((message) => `message:${message.id}`),
    ...pendingInputBuffers.map((buffer) => `pending:${buffer.id}`),
  ];
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
  /** not yet model turn  to not injected pending input buffers */
  pendingInputBuffers: PendingInputBuffer[];
  activeAgent: AgentResponse | null;
  sessionId?: string | null;
  isResponsePending: boolean;
  isWritePending: boolean;
  isModelResponsePending: boolean;
  /** current workspace handle */
  handle: string;
  onSendInput: (
    message: string,
    action?: ChatAction | null,
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
  /** older messages  withtext */
  onLoadMore: () => void;
  /** newer messages  withtext */
  onLoadNewer: () => void;
  /** latest reset */
  onResetToLatest: () => void;
  /** submit user message edit */
  onSubmitMessageEdit: (
    messageId: string,
    message: string,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** Context compaction whether in progress */
  isCompacting: boolean;
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
  /** Workspace panel container output */
  workspacePanel: WorkspacePanelContainerOutput;
  /** current session goal snapshot */
  goal: GoalStateSnapshot;
  /** current session todo snapshot */
  todo: TodoStateSnapshot;
}

export function ChatView({
  chatViewState,
  chatTimelineState,
  messages,
  pendingInputBuffers,
  activeAgent,
  sessionId = null,
  isResponsePending,
  isWritePending,
  isModelResponsePending,
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
  isCompacting,
  wasCommandBlocked,
  isStopAvailable,
  isStopPending,
  onStopRequest,
  inputActions,
  authorizationRequests,
  onAuthorizationComplete,
  workspacePanel,
  goal,
  todo,
}: ChatViewProps): React.ReactElement {
  const t = useTranslations("chat");
  // Subagent detail modal status
  const [selectedSubagent, setSelectedSubagent] = useState<{
    sessionId: string;
    name: string;
  } | null>(null);
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
    clearDoneFiles,
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
  const lastUserScrollIntentAtRef = useRef(0);
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
  const hasTimelineItems =
    messages.length > 0 || pendingInputBuffers.length > 0;
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
      setEditingMessage({ messageId: message.id, content: message.content });
    },
    [clearFiles],
  );

  const handleCancelEdit = useCallback((): void => {
    setEditingMessage(null);
  }, []);

  const handleSubmitInput = useCallback(
    async (
      message: string,
      action?: ChatAction | null,
      attachments?: UploadedFile[],
    ): Promise<boolean> => {
      if (!editingMessage) {
        return onSendInput(message, action, attachments);
      }
      if (isResponsePending || action) {
        return false;
      }
      const sent = await onSubmitMessageEdit(
        editingMessage.messageId,
        message,
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
  const savedScrollRef = useRef<{
    scrollHeight: number;
    scrollTop: number;
  } | null>(null);

  const markProgrammaticScroll = useCallback((): void => {
    programmaticScrollUntilRef.current =
      performance.now() + PROGRAMMATIC_SCROLL_GUARD_MS;
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
    requestAnimationFrame(pinToBottom);
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
      const diff = viewport.scrollHeight - saved.scrollHeight;
      markProgrammaticScroll();
      viewport.scrollTop = saved.scrollTop + diff;
      savedScrollRef.current = null;
      prevMessageIdsRef.current = new Set(
        getTimelineItemIds(messages, pendingInputBuffers),
      );
    }
  }, [messages, pendingInputBuffers, isLoadingMore, markProgrammaticScroll]);

  // initial load when paint before to bottom with scroll.
  // useEffect(paint after) itext useLayoutEffect(paint before) in handledtext
  // scrollTop=0 status in scroll event onLoadMore misfire text prevention.
  useLayoutEffect(() => {
    if (
      !isInitialScrollRef.current ||
      (messages.length === 0 && pendingInputBuffers.length === 0) ||
      savedScrollRef.current
    ) {
      return;
    }
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const storedScrollState = pendingInitialScrollRestoreRef.current;
    pendingInitialScrollRestoreRef.current = null;
    if (
      storedScrollState !== null &&
      !storedScrollState.following &&
      storedScrollState.distanceFromBottom >= FOLLOW_EXIT_THRESHOLD
    ) {
      markProgrammaticScroll();
      viewport.scrollTop = Math.max(
        0,
        viewport.scrollHeight -
          viewport.clientHeight -
          storedScrollState.distanceFromBottom,
      );
      isFollowingLatestRef.current = false;
    } else {
      pinToBottom();
      isFollowingLatestRef.current = true;
    }
    isInitialScrollRef.current = false;
    prevMessageIdsRef.current = new Set(
      getTimelineItemIds(messages, pendingInputBuffers),
    );

    // text after next frame pagination enable (sectext scroll insidetext waiting)
    requestAnimationFrame(() => {
      isReadyForPaginationRef.current = true;
    });
  }, [messages, pendingInputBuffers, markProgrammaticScroll, pinToBottom]);

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
    if (
      chatViewState.type === "LOADING_HISTORY" &&
      messages.length === 0 &&
      pendingInputBuffers.length === 0
    ) {
      isInitialScrollRef.current = true;
      isReadyForPaginationRef.current = false;
      isFollowingLatestRef.current = true;
      setShowNewMessageChip(false);
      prevMessageIdsRef.current = new Set();
    }
  }, [chatViewState.type, messages.length, pendingInputBuffers.length]);

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
    const timelineItemIds = getTimelineItemIds(messages, pendingInputBuffers);
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
  }, [messages, pendingInputBuffers, schedulePinToBottom]);

  // integration scroll handler: bottom detection + new message chip release + older messages  withtext + mobile header hide/display
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const markUserScrollIntent = (): void => {
      lastUserScrollIntentAtRef.current = performance.now();
    };

    const handleScroll = (): void => {
      const scrollTop = viewport.scrollTop;

      // (1) follow detection update
      const distanceFromBottom = scrollDistanceFromBottom(viewport);
      const atFollowBoundary = distanceFromBottom <= BOTTOM_FOLLOW_THRESHOLD;
      const now = performance.now();
      const inProgrammaticScroll = now < programmaticScrollUntilRef.current;
      if (atFollowBoundary) {
        isFollowingLatestRef.current = true;
      } else if (
        !inProgrammaticScroll &&
        distanceFromBottom >= FOLLOW_EXIT_THRESHOLD
      ) {
        isFollowingLatestRef.current = false;
      }
      persistScrollState(viewport, isFollowingLatestRef.current);

      // bottom or bottom bounce area to alsotextwhen new message chip hide.
      // text bottom in text textonly with detached/buffering switchdoes not..
      if (atFollowBoundary) {
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
    viewport.addEventListener("pointerdown", markUserScrollIntent, {
      passive: true,
    });
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      viewport.removeEventListener("wheel", markUserScrollIntent);
      viewport.removeEventListener("touchstart", markUserScrollIntent);
      viewport.removeEventListener("touchmove", markUserScrollIntent);
      viewport.removeEventListener("pointerdown", markUserScrollIntent);
      viewport.removeEventListener("scroll", handleScroll);
    };
  }, [
    chatTimelineState.type,
    hasDetachedNewer,
    isMobile,
    hasMore,
    isLoadingMore,
    isLoadingNewer,
    onLoadMore,
    onLoadNewer,
    onResetToLatest,
    persistScrollState,
  ]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (
        event.key === "ArrowUp" ||
        event.key === "ArrowDown" ||
        event.key === "PageUp" ||
        event.key === "PageDown" ||
        event.key === "Home" ||
        event.key === "End" ||
        event.key === " "
      ) {
        lastUserScrollIntentAtRef.current = performance.now();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

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
            {messages.length === 0 &&
            pendingInputBuffers.length === 0 &&
            !isResponsePending ? (
              <Center py="xl">
                <Text c="dimmed" size="sm">
                  {t("startConversation")}
                </Text>
              </Center>
            ) : (
              <Stack gap={0}>
                {messages.map((msg, index) => {
                  if (msg.role === "compaction") {
                    return (
                      <CompactionDivider key={msg.id} content={msg.content} />
                    );
                  }
                  if (
                    msg.role === "compaction_started" ||
                    msg.role === "subagent_end" ||
                    isBoundaryMessage(msg)
                  ) {
                    return null;
                  }
                  const boundaryControls = getBoundaryControls(messages, index);
                  const dimmedByEdit =
                    editingMessageIndex !== null &&
                    index >= editingMessageIndex;
                  const editableUserMessage =
                    msg.role === "user" &&
                    Boolean(msg.content) &&
                    msg.status !== "partial" &&
                    index > latestCompactionIndex &&
                    !isResponsePending;
                  if (msg.role === "subagent_start") {
                    const subSessionId =
                      msg.metadata?.subagent_session_id ?? null;
                    const subName = msg.metadata?.subagent_name ?? "Subagent";
                    // subagent_end if absent not yet run during
                    const endMsg = messages.find(
                      (m) =>
                        m.role === "subagent_end" &&
                        m.metadata?.subagent_session_id === subSessionId,
                    );
                    const isRunning = !endMsg;
                    return (
                      <Fragment key={msg.id}>
                        <SubagentBlock
                          message={msg}
                          isRunning={isRunning}
                          resultText={endMsg?.content}
                          onClick={() =>
                            setSelectedSubagent(
                              subSessionId
                                ? { sessionId: subSessionId, name: subName }
                                : null,
                            )
                          }
                        />
                        <TurnDivider usage={boundaryControls.usage} />
                      </Fragment>
                    );
                  }
                  return (
                    <Fragment key={msg.id}>
                      <MessageBubble
                        message={msg}
                        dimmed={dimmedByEdit}
                        editable={editableUserMessage}
                        onEdit={() => handleStartEdit(msg)}
                      />
                      <TurnDivider usage={boundaryControls.usage} />
                    </Fragment>
                  );
                })}
                {authorizationRequests.map((req) => (
                  <AuthorizationRequestBubble
                    key={req.toolkitId}
                    toolkitName={req.toolkitName}
                    authorizationUrl={req.authorizationUrl}
                    onAuthorized={() => onAuthorizationComplete(req.toolkitId)}
                  />
                ))}
                {chatTimelineState.type === "LATEST_FOLLOWING" &&
                  isModelResponsePending &&
                  shouldShowPendingIndicator(messages) && <AgentRunIndicator />}
                {chatTimelineState.type === "LATEST_FOLLOWING" &&
                  isCompacting && <CompactionIndicator />}
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
                size="lg"
                variant="filled"
                color="blue"
                rightSection={<IconArrowDown size={14} />}
                onClick={scrollToBottom}
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
                isUploading={isUploading || isWritePending}
                pendingFiles={pendingFiles}
                goal={editingMessage === null ? goal : null}
                todo={editingMessage === null ? todo : null}
                onClearGoal={onClearGoal}
                onUpdateGoal={onUpdateGoal}
                onPauseGoal={onPauseGoal}
                onResumeGoal={onResumeGoal}
                uploadAll={uploadAll}
                onSendInput={handleSubmitInput}
                clearDoneFiles={clearDoneFiles}
                resetDoneFiles={resetDoneFiles}
                addFiles={addFiles}
                removeFile={removeFile}
                onAfterSend={handleAfterSend}
                onFocus={handleInputFocus}
                wasCommandBlocked={wasCommandBlocked}
                isStopAvailable={isStopAvailable}
                isStopPending={isStopPending}
                onStopRequest={onStopRequest}
                inputActions={inputActions}
                editingMessageId={editingMessage?.messageId ?? null}
                editingInitialValue={editingMessage?.content ?? null}
                onCancelEdit={handleCancelEdit}
                editSendDisabled={editingMessage !== null && isResponsePending}
              />
            </Box>
          </Box>
        </Box>

        {/* Subagent detail modal */}
        {selectedSubagent && (
          <SubagentDetailModal
            opened={true}
            onClose={() => setSelectedSubagent(null)}
            sessionId={selectedSubagent.sessionId}
            subagentName={selectedSubagent.name}
            isRunning={
              !messages.some(
                (m) =>
                  m.role === "subagent_end" &&
                  m.metadata?.subagent_session_id ===
                    selectedSubagent.sessionId,
              )
            }
          />
        )}
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
