"use client";

/**
 * Subagent detail modal.
 *
 * Subagent session of message existing chat UI (MessageBubble) reuse and display..
 * mobile: fullScreen, desktop: centered modal.
 *
 * Scroll policy (ChatViewand same):
 * - initial load: useLayoutEffect with bottom scroll → pagination enable
 * - bottomwhen: new message when arrives auto-scroll
 * - bottom when not: new message when arrives "new message" show chip
 * - above with scrollwhen older messages  withtext (pagination), preserve scroll position
 */

import {
  Badge,
  Box,
  Center,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconArrowDown, IconRobot } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useSubagentSession } from "../hooks/useSubagentSession";
import { MessageBubble } from "./MessageBubble";
import { TurnDivider } from "./TurnDivider";
import type { ChatMessage } from "../types";

/** older messages load trigger scroll position (px) */
const LOAD_MORE_THRESHOLD = 100;
/** bottom detection allow tolerance (px) */
const BOTTOM_THRESHOLD = 50;

/** viewport bottom near detection */
function checkIsAtBottom(viewport: HTMLDivElement): boolean {
  const { scrollTop, scrollHeight, clientHeight } = viewport;
  return scrollHeight - scrollTop - clientHeight <= BOTTOM_THRESHOLD;
}

/** completion marker message below control with renderingtext abovetext identify.. */
function isBoundaryMessage(message: ChatMessage): boolean {
  return message.role === "turn_complete" || message.role === "run_complete";
}

/** subagent modal in actual message with display row checks.. */
function isVisibleMessage(message: ChatMessage): boolean {
  return !isBoundaryMessage(message);
}

/** display message bar with after of turn usage marker find.. */
function getTurnUsageAfter(
  messages: ChatMessage[],
  messageIndex: number,
): Record<string, unknown> | null {
  for (let i = messageIndex + 1; i < messages.length; i += 1) {
    const next = messages[i];
    if (!next) {
      continue;
    }
    if (isVisibleMessage(next)) {
      break;
    }
    if (next.role === "turn_complete") {
      return next.usage ?? null;
    }
  }
  return null;
}

interface SubagentDetailModalProps {
  /** Modal whether open */
  opened: boolean;
  /** Modal close callback */
  onClose: () => void;
  /** Subagent session ID */
  sessionId: string | null;
  /** Subagent name */
  subagentName: string;
  /** Subagent run duringwhether whether */
  isRunning: boolean;
}

export function SubagentDetailModal({
  opened,
  onClose,
  sessionId,
  subagentName,
  isRunning,
}: SubagentDetailModalProps): React.ReactElement {
  const t = useTranslations("chat.subagent");
  const tChat = useTranslations("chat");
  const isMobile = useMediaQuery("(max-width: 768px)");

  const { messages, isLoading, hasMore, isLoadingMore, onLoadMore } =
    useSubagentSession({
      sessionId: opened ? sessionId : null,
      isRunning,
    });

  // --- scroll status (ChatView pattern copy) ---
  const viewportRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const [showNewMessageChip, setShowNewMessageChip] = useState(false);
  const prevMessageIdsRef = useRef<Set<string>>(new Set());
  const isReadyForPaginationRef = useRef(false);
  const isInitialScrollRef = useRef(true);

  // pagination preserve scroll position
  const isLoadingMoreRef = useRef(false);
  const savedScrollRef = useRef<{
    scrollHeight: number;
    scrollTop: number;
  } | null>(null);

  // modal close when scroll status reset
  useEffect(() => {
    if (!opened) {
      isInitialScrollRef.current = true;
      isReadyForPaginationRef.current = false;
      isAtBottomRef.current = true;
      setShowNewMessageChip(false);
      prevMessageIdsRef.current = new Set();
      savedScrollRef.current = null;
    }
  }, [opened]);

  // isLoadingMore when switching scroll position save
  useEffect(() => {
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

  // pagination after scroll position restore
  useLayoutEffect(() => {
    const saved = savedScrollRef.current;
    const viewport = viewportRef.current;
    if (saved && viewport && !isLoadingMore) {
      const diff = viewport.scrollHeight - saved.scrollHeight;
      viewport.scrollTop = saved.scrollTop + diff;
      savedScrollRef.current = null;
    }
  }, [messages, isLoadingMore]);

  // initial load when bottom scroll (useLayoutEffect with paint before handle)
  useLayoutEffect(() => {
    if (
      !isInitialScrollRef.current ||
      messages.length === 0 ||
      savedScrollRef.current
    ) {
      return;
    }
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    viewport.scrollTop = viewport.scrollHeight;
    isAtBottomRef.current = true;
    isInitialScrollRef.current = false;
    prevMessageIdsRef.current = new Set(messages.map((m) => m.id));

    // text after next frame pagination enable
    requestAnimationFrame(() => {
      isReadyForPaginationRef.current = true;
    });
  }, [messages]);

  // conditional scroll when messages change (initial load except)
  useEffect(() => {
    if (isInitialScrollRef.current || savedScrollRef.current) {
      return;
    }

    const prevIds = prevMessageIdsRef.current;
    const lastMessage = messages[messages.length - 1];
    const hasNewMessage = lastMessage != null && !prevIds.has(lastMessage.id);

    // snapshot update
    prevMessageIdsRef.current = new Set(messages.map((m) => m.id));

    // streaming text update: bottomwhen follow
    if (!hasNewMessage) {
      if (isAtBottomRef.current && viewportRef.current) {
        viewportRef.current.scrollTo({
          top: viewportRef.current.scrollHeight,
          behavior: "instant",
        });
      }
      return;
    }

    // new message arrival
    if (isAtBottomRef.current) {
      if (viewportRef.current) {
        viewportRef.current.scrollTo({
          top: viewportRef.current.scrollHeight,
          behavior: "smooth",
        });
      }
    } else {
      setShowNewMessageChip(true);
    }
  }, [messages]);

  // integration scroll handler: bottom detection + chip release + pagination trigger
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const handleScroll = (): void => {
      const scrollTop = viewport.scrollTop;

      // bottom detection update
      const atBottom = checkIsAtBottom(viewport);
      isAtBottomRef.current = atBottom;

      if (atBottom) {
        setShowNewMessageChip(false);
      }

      // older messages load trigger
      if (
        scrollTop <= LOAD_MORE_THRESHOLD &&
        hasMore &&
        !isLoadingMore &&
        isReadyForPaginationRef.current
      ) {
        onLoadMore();
      }
    };

    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, [hasMore, isLoadingMore, onLoadMore]);

  /** bottom with scroll + chip hide */
  const scrollToBottom = useCallback(() => {
    setShowNewMessageChip(false);
    isAtBottomRef.current = true;
    if (viewportRef.current) {
      viewportRef.current.scrollTo({
        top: viewportRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, []);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="xs">
          <IconRobot size={18} />
          <Text fw={600} size="sm">
            {subagentName}
          </Text>
          <Badge size="xs" variant="light" color={isRunning ? "blue" : "green"}>
            {isRunning ? t("running") : t("completed")}
          </Badge>
        </Group>
      }
      fullScreen={!!isMobile}
      centered={!isMobile}
      size="xl"
      styles={{
        body: {
          overflow: "hidden",
          ...(isMobile && {
            display: "flex",
            flexDirection: "column" as const,
            flex: 1,
          }),
        },
        ...(isMobile && {
          content: { display: "flex", flexDirection: "column" as const },
        }),
      }}
    >
      {isLoading ? (
        <Center py="xl">
          <Stack align="center" gap="md">
            <Loader size="md" />
            <Text c="dimmed" size="sm">
              {t("loadingHistory")}
            </Text>
          </Stack>
        </Center>
      ) : messages.length === 0 ? (
        <Center py="xl">
          <Text c="dimmed" size="sm">
            {t("noMessages")}
          </Text>
        </Center>
      ) : (
        <Box
          style={
            isMobile
              ? {
                  display: "flex",
                  flexDirection: "column",
                  flex: 1,
                  overflow: "hidden",
                  position: "relative",
                }
              : { position: "relative" }
          }
        >
          <ScrollArea.Autosize
            viewportRef={viewportRef}
            {...(!isMobile && { mah: "calc(80vh - 80px)" })}
            {...(isMobile && { style: { flex: 1, overflow: "hidden" } })}
            styles={{ content: { minWidth: 0 } }}
          >
            <Box px="xs">
              <Stack gap={0}>
                {/* older messages loading indicator */}
                {isLoadingMore && (
                  <Center py="sm">
                    <Loader size="sm" />
                  </Center>
                )}
                {messages.map((msg, index) => {
                  if (isBoundaryMessage(msg)) {
                    return null;
                  }
                  const usage = getTurnUsageAfter(messages, index);
                  return (
                    <Fragment key={msg.id}>
                      <MessageBubble message={msg} />
                      <TurnDivider usage={usage} />
                    </Fragment>
                  );
                })}
                {isRunning && (
                  <Center py="sm">
                    <Group gap="xs">
                      <Loader size={14} />
                      <Text size="sm" c="dimmed">
                        {t("running")}
                      </Text>
                    </Group>
                  </Center>
                )}
              </Stack>
            </Box>
          </ScrollArea.Autosize>

          {/* new message notice chip */}
          {showNewMessageChip && (
            <Box
              style={{
                position: "absolute",
                bottom: 16,
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: 2,
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
                {tChat("newMessage")}
              </Badge>
            </Box>
          )}
        </Box>
      )}
    </Modal>
  );
}
