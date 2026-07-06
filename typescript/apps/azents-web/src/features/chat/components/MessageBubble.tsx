"use client";

/**
 * chat message bubble component.
 *
 * role(user/assistant) to according to displays messages with different style.
 * streaming message cursor blink animation display.
 */

import {
  ActionIcon,
  Box,
  Collapse,
  Group,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import {
  IconBook,
  IconCheck,
  IconChevronRight,
  IconClock,
  IconPencil,
  IconTargetArrow,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChatCopyButton } from "./ChatCopyButton";
import { FileAttachmentList } from "./FileAttachmentList";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import { MarkdownContent } from "./MarkdownContent";
import classes from "./MessageBubble.module.css";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import { RunRetryCard } from "./RunRetryCard";
import { ToolCallCard } from "./ToolCallCard";
import type { ChatMessage } from "../types";

interface FailedRunRetryAction {
  canRetry: boolean;
  isPending: boolean;
  onRetry: () => void;
}

interface MessageBubbleProps {
  message: ChatMessage;
  dimmed?: boolean;
  editable?: boolean;
  onEdit?: () => void;
  failedRunRetryAction?: FailedRunRetryAction | null;
}

interface TextMessageProps {
  message: ChatMessage;
  hasContent: boolean;
  hasReasoning: boolean;
}

interface MessageSurfaceTimeContextValue {
  isTouchPrimary: boolean;
  timeVisible: boolean;
  showTimeForTouch: () => void;
}

type MessageActionAlign = "assistant" | "user";
type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

const MessageSurfaceTimeContext =
  createContext<MessageSurfaceTimeContextValue | null>(null);
const TIMESTAMP_FADE_DURATION_MS = 160;

function formatRelativeTime(iso: string, t: ChatTranslator): string {
  const createdAt = new Date(iso).getTime();
  if (!Number.isFinite(createdAt)) {
    return "";
  }

  const diff = Math.max(0, Date.now() - createdAt);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) {
    return t("justNow");
  }
  if (minutes < 60) {
    return t("minutesAgo", { count: minutes });
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return t("hoursAgo", { count: hours });
  }

  const days = Math.floor(hours / 24);
  return t("daysAgo", { count: days });
}

function formatDuration(
  totalSeconds: number | null,
  t: ChatTranslator,
): string {
  if (totalSeconds === null || totalSeconds < 0) {
    return t("goalBriefing.unknownDuration");
  }

  const seconds = Math.floor(totalSeconds % 60);
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  const parts: string[] = [];

  if (hours > 0) {
    parts.push(t("goalBriefing.durationHours", { count: hours }));
  }
  if (minutes > 0) {
    parts.push(t("goalBriefing.durationMinutes", { count: minutes }));
  }
  if (parts.length === 0 || seconds > 0) {
    parts.push(t("goalBriefing.durationSeconds", { count: seconds }));
  }

  return parts.join(" ");
}

function numberMetadataValue(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatFullDateTime(iso: string, locale: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) {
    return iso;
  }

  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

function getNextRelativeTimeDelay(iso: string): number {
  const createdAt = new Date(iso).getTime();
  if (!Number.isFinite(createdAt)) {
    return 60_000;
  }

  const diff = Math.max(0, Date.now() - createdAt);
  if (diff < 60_000) {
    return 60_000 - diff;
  }

  return 60_000 - (diff % 60_000);
}

function MessageTimestamp({
  createdAt,
}: {
  createdAt: string;
}): React.ReactElement {
  const locale = useLocale();
  const t = useTranslations("chat");
  const surfaceTime = useContext(MessageSurfaceTimeContext);
  const isTouchPrimary = surfaceTime?.isTouchPrimary ?? false;
  const surfaceTimeVisible = surfaceTime?.timeVisible ?? false;
  const [tooltipOpened, setTooltipOpened] = useState(false);
  const [relativeTimeTick, setRelativeTimeTick] = useState(0);

  const relativeTime = formatRelativeTime(createdAt, t);
  const fullDateTime = useMemo(
    () => formatFullDateTime(createdAt, locale),
    [createdAt, locale],
  );

  useEffect(() => {
    if (!surfaceTimeVisible) {
      setTooltipOpened(false);
    }
  }, [surfaceTimeVisible]);

  useEffect(() => {
    if (!isTouchPrimary || !tooltipOpened) {
      return;
    }

    function hideTooltipOnScroll(): void {
      setTooltipOpened(false);
    }

    window.addEventListener("scroll", hideTooltipOnScroll, true);

    return () => {
      window.removeEventListener("scroll", hideTooltipOnScroll, true);
    };
  }, [isTouchPrimary, tooltipOpened]);

  useEffect(() => {
    const delay = getNextRelativeTimeDelay(createdAt);
    const timer = setTimeout(() => {
      setRelativeTimeTick((current) => current + 1);
    }, delay);

    return () => {
      clearTimeout(timer);
    };
  }, [createdAt, relativeTimeTick]);

  function showTouchTooltip(event: React.PointerEvent<HTMLElement>): void {
    if (!isTouchPrimary || surfaceTime === null) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    surfaceTime.showTimeForTouch();
    setTooltipOpened(true);
  }

  function hideTouchTooltip(event: React.PointerEvent<HTMLElement>): void {
    if (!isTouchPrimary) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    setTooltipOpened(false);
  }

  const tooltipLabel = isTouchPrimary ? (
    <Box
      component="span"
      className={classes.messageTooltipLabel}
      onPointerDown={hideTouchTooltip}
    >
      {fullDateTime}
    </Box>
  ) : (
    fullDateTime
  );

  const timestamp = (
    <Text
      component="time"
      dateTime={createdAt}
      size="xs"
      c="dimmed"
      className={classes.messageTime}
      aria-label={fullDateTime}
      tabIndex={0}
      onPointerDown={showTouchTooltip}
    >
      {relativeTime}
    </Text>
  );

  if (isTouchPrimary) {
    return (
      <Tooltip
        label={tooltipLabel}
        withArrow
        opened={tooltipOpened && surfaceTimeVisible}
        classNames={{ tooltip: classes.messageTooltip }}
        transitionProps={{
          transition: "fade",
          duration: TIMESTAMP_FADE_DURATION_MS,
        }}
      >
        {timestamp}
      </Tooltip>
    );
  }

  return (
    <Tooltip
      label={tooltipLabel}
      withArrow
      transitionProps={{
        transition: "fade",
        duration: TIMESTAMP_FADE_DURATION_MS,
      }}
    >
      {timestamp}
    </Tooltip>
  );
}

function MessageSurface({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const isTouchPrimary = useMediaQuery("(hover: none)");
  const [timeVisible, setTimeVisible] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current);
      }
    };
  }, []);

  const showTimeForTouch = useCallback((): void => {
    if (!isTouchPrimary) {
      return;
    }

    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
    }

    setTimeVisible(true);
    hideTimerRef.current = setTimeout(() => {
      setTimeVisible(false);
      hideTimerRef.current = null;
    }, 5000);
  }, [isTouchPrimary]);

  const surfaceTime = useMemo(
    () => ({
      isTouchPrimary,
      timeVisible,
      showTimeForTouch,
    }),
    [isTouchPrimary, showTimeForTouch, timeVisible],
  );

  return (
    <MessageSurfaceTimeContext.Provider value={surfaceTime}>
      <Box
        className={classes.messageSurface}
        data-time-visible={timeVisible}
        onPointerDown={showTimeForTouch}
      >
        {children}
      </Box>
    </MessageSurfaceTimeContext.Provider>
  );
}

function ThinkingBlock({
  hasContent,
  reasoningSummary,
}: {
  hasContent: boolean;
  reasoningSummary: string;
}): React.ReactElement {
  const t = useTranslations("chat");
  const [thinkingOpened, { toggle: toggleThinking }] = useDisclosure(false);

  return (
    <Box mb={hasContent ? "xs" : 0}>
      <Group
        gap={rem(4)}
        wrap="nowrap"
        style={{ cursor: "pointer", userSelect: "none", width: "100%" }}
        onClick={toggleThinking}
      >
        <IconChevronRight
          size={rem(12)}
          style={{
            flexShrink: 0,
            transform: thinkingOpened ? "rotate(90deg)" : "none",
            transition: "transform 200ms",
          }}
          color="var(--mantine-color-dimmed)"
        />
        <Text
          size="xs"
          c="dimmed"
          fw={500}
          lineClamp={1}
          style={{ flex: 1, minWidth: 0 }}
        >
          {t("thinkingLabel")}
        </Text>
      </Group>
      <Collapse expanded={thinkingOpened}>
        <ScrollArea.Autosize mah={rem(300)} mt={rem(4)}>
          <Box c="dimmed">
            <MarkdownContent>{reasoningSummary}</MarkdownContent>
          </Box>
        </ScrollArea.Autosize>
      </Collapse>
    </Box>
  );
}

function TextMessageContent({
  message,
  hasContent,
  hasReasoning,
}: TextMessageProps): React.ReactElement {
  const t = useTranslations("chat");

  return (
    <>
      {hasReasoning && (
        <ThinkingBlock
          hasContent={hasContent}
          reasoningSummary={message.reasoningSummary ?? ""}
        />
      )}

      {message.content && (
        <>
          <MarkdownContent>{message.content}</MarkdownContent>
          {message.status === "partial" && (
            <Text component="span" fw={700} size="sm">
              |
            </Text>
          )}
        </>
      )}

      {/* streamingand content if absent loading display (reasoning existstextwhen above of Thinking block shown instead) */}
      {message.status === "partial" && !message.content && !hasReasoning && (
        <Text size="sm" c="dimmed">
          {t("thinking")}
        </Text>
      )}
    </>
  );
}

function MessageActionRow({
  content,
  createdAt,
  align,
  editable = false,
  onEdit,
}: {
  content: string;
  createdAt: string;
  align: MessageActionAlign;
  editable?: boolean;
  onEdit?: () => void;
}): React.ReactElement {
  const t = useTranslations("chat");
  const actionRowClassName =
    align === "assistant"
      ? `${classes.actionRow} ${classes.actionRowAssistant}`
      : `${classes.actionRow} ${classes.actionRowUser}`;
  const copyButton = (
    <ChatCopyButton
      value={content}
      copyLabel={t("copy")}
      copiedLabel={t("copied")}
      position={align === "user" ? "left" : "right"}
    />
  );

  return (
    <Group
      gap={rem(4)}
      mt={rem(4)}
      wrap="nowrap"
      className={actionRowClassName}
    >
      {align === "user" && <MessageTimestamp createdAt={createdAt} />}
      {copyButton}
      {editable && onEdit && (
        <Tooltip label={t("editMessage")} withArrow position="left">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            onClick={onEdit}
            aria-label={t("editMessage")}
          >
            <IconPencil size={14} />
          </ActionIcon>
        </Tooltip>
      )}
      {align === "assistant" && <MessageTimestamp createdAt={createdAt} />}
    </Group>
  );
}

function UserTextMessage({
  message,
  hasContent,
  hasReasoning,
  editable = false,
  onEdit,
}: TextMessageProps & {
  editable?: boolean;
  onEdit?: () => void;
}): React.ReactElement {
  if (message.action) {
    return (
      <MessageSurface>
        <InputBufferBubbleFrame
          content={message.content ?? ""}
          action={message.action}
          attachments={[]}
          attachmentFiles={message.attachments}
          opacity={1}
          actions={
            message.content && message.status !== "partial" ? (
              <MessageActionRow
                content={message.content}
                createdAt={message.createdAt}
                align="user"
                editable={editable}
                onEdit={onEdit}
              />
            ) : null
          }
        />
      </MessageSurface>
    );
  }

  return (
    <Group
      align="flex-start"
      gap="sm"
      justify="flex-end"
      wrap="nowrap"
      mb="md"
      w="100%"
      style={{ minWidth: 0 }}
    >
      <Box maw="75%" style={{ minWidth: 0 }}>
        <MessageSurface>
          {message.attachments && message.attachments.length > 0 && (
            <FileAttachmentList files={message.attachments} />
          )}

          {(hasContent || hasReasoning || message.status === "partial") && (
            <Paper
              px="sm"
              py="2xs"
              radius="lg"
              bg="blue.6"
              c="white"
              style={{
                width: "fit-content",
                maxWidth: "100%",
                minWidth: 0,
                overflowWrap: "anywhere",
                borderTopRightRadius: rem(4),
                marginLeft: "auto",
              }}
            >
              <TextMessageContent
                message={message}
                hasContent={hasContent}
                hasReasoning={hasReasoning}
              />
            </Paper>
          )}

          {message.content && message.status !== "partial" && (
            <MessageActionRow
              content={message.content}
              createdAt={message.createdAt}
              align="user"
              editable={editable}
              onEdit={onEdit}
            />
          )}
        </MessageSurface>
      </Box>
    </Group>
  );
}

function AssistantTextMessage({
  message,
  hasContent,
  hasReasoning,
}: TextMessageProps): React.ReactElement {
  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <Box style={{ maxWidth: "100%", minWidth: 0, overflowWrap: "anywhere" }}>
        <MessageSurface>
          {(hasContent || hasReasoning || message.status === "partial") && (
            <TextMessageContent
              message={message}
              hasContent={hasContent}
              hasReasoning={hasReasoning}
            />
          )}

          {message.attachments && message.attachments.length > 0 && (
            <FileAttachmentList files={message.attachments} />
          )}

          {message.content && message.status !== "partial" && (
            <MessageActionRow
              content={message.content}
              createdAt={message.createdAt}
              align="assistant"
            />
          )}
        </MessageSurface>
      </Box>
    </Box>
  );
}

function GoalControlMessage({ label }: { label: string }): React.ReactElement {
  return (
    <Group gap={rem(6)} c="dimmed" mb="md" wrap="nowrap">
      <IconTargetArrow aria-hidden="true" size={14} stroke={1.8} />
      <Text size="xs">{label}</Text>
    </Group>
  );
}

function stripMarkdownFrontmatter(content: string): string {
  const frontmatter = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/u.exec(
    content.replace(/^\uFEFF/u, ""),
  );
  if (frontmatter === null || frontmatter.index !== 0) {
    return content;
  }
  return content.slice(frontmatter[0].length).trimStart();
}

function SkillLoadedControlMessage({
  message,
}: {
  message: ChatMessage;
}): React.ReactElement {
  const t = useTranslations("chat");
  const [opened, { toggle }] = useDisclosure(false);
  const name = message.metadata?.name || t("skillLoaded.unknownSkill");
  const body = useMemo(
    () => stripMarkdownFrontmatter(message.content ?? ""),
    [message.content],
  );

  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <Stack gap={rem(6)} maw={rem(720)}>
        <Group
          gap={rem(6)}
          c="dimmed"
          wrap="nowrap"
          role="button"
          tabIndex={0}
          style={{ cursor: "pointer", userSelect: "none" }}
          onClick={toggle}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              toggle();
            }
          }}
        >
          <IconChevronRight
            aria-hidden="true"
            size={14}
            stroke={1.8}
            style={{
              flexShrink: 0,
              transform: opened ? "rotate(90deg)" : "none",
              transition: "transform 160ms",
            }}
          />
          <IconBook aria-hidden="true" size={14} stroke={1.8} />
          <Text size="xs" fw={600} lineClamp={1} style={{ minWidth: 0 }}>
            {t("skillLoaded.title", { name })}
          </Text>
        </Group>
        <Collapse expanded={opened}>
          <Paper
            withBorder
            radius="md"
            p="sm"
            bg="var(--mantine-color-body)"
            style={{ minWidth: 0, overflow: "hidden" }}
          >
            <ScrollArea.Autosize
              mah={rem(360)}
              scrollbars="y"
              style={{ maxWidth: "100%" }}
            >
              <Box className={classes.skillLoadedBody}>
                <MarkdownContent>{body}</MarkdownContent>
              </Box>
            </ScrollArea.Autosize>
          </Paper>
        </Collapse>
      </Stack>
    </Box>
  );
}

function InterruptedControlMessage(): React.ReactElement {
  const t = useTranslations("chat");

  return (
    <Group gap="sm" c="dimmed" mb="md" w="100%" wrap="nowrap">
      <Box h={rem(1)} bg="var(--mantine-color-default-border)" flex={1} />
      <Text size="xs" fw={600}>
        {t("interruptedIndicator")}
      </Text>
      <Box h={rem(1)} bg="var(--mantine-color-default-border)" flex={1} />
    </Group>
  );
}

function GoalBriefingCard({
  message,
}: {
  message: ChatMessage;
}): React.ReactElement {
  const locale = useLocale();
  const t = useTranslations("chat");
  const objective = message.metadata?.objective || message.content || "";
  const completedAt = message.metadata?.completed_at || message.createdAt;
  const durationSeconds = numberMetadataValue(
    message.metadata?.duration_seconds ?? null,
  );

  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <Paper
        withBorder
        radius="lg"
        p="sm"
        bg="var(--mantine-color-body)"
        style={{ maxWidth: rem(520) }}
      >
        <Stack gap="sm">
          <Group gap="xs" wrap="nowrap">
            <IconCheck
              aria-hidden="true"
              size={18}
              stroke={1.8}
              color="var(--mantine-color-green-5)"
              style={{ flexShrink: 0 }}
            />
            <Text fw={600} size="sm">
              {t("goalBriefing.title")}
            </Text>
          </Group>
          <Stack gap={rem(6)}>
            <Text size="xs" c="dimmed" fw={600} tt="uppercase" lts={rem(0.4)}>
              {t("goalBriefing.goal")}
            </Text>
            <Text size="sm" style={{ overflowWrap: "anywhere" }}>
              {objective}
            </Text>
          </Stack>
          <Group gap="lg" wrap="wrap">
            <Group gap={rem(6)} wrap="nowrap">
              <IconClock
                aria-hidden="true"
                size={15}
                stroke={1.8}
                color="var(--mantine-color-dimmed)"
              />
              <Box>
                <Text size="xs" c="dimmed">
                  {t("goalBriefing.duration")}
                </Text>
                <Text size="sm" fw={500}>
                  {formatDuration(durationSeconds, t)}
                </Text>
              </Box>
            </Group>
            <Box>
              <Text size="xs" c="dimmed">
                {t("goalBriefing.completedAt")}
              </Text>
              <Text size="sm" fw={500}>
                {formatFullDateTime(completedAt, locale)}
              </Text>
            </Box>
          </Group>
        </Stack>
      </Paper>
    </Box>
  );
}

function ErrorTextMessage({
  message,
  failedRunRetryAction = null,
}: {
  message: ChatMessage;
  failedRunRetryAction?: FailedRunRetryAction | null;
}): React.ReactElement {
  if (message.failedRunFailure) {
    return (
      <RunRetryCard
        variant="terminal"
        message={message.content ?? ""}
        failure={message.failedRunFailure}
        canRetry={failedRunRetryAction?.canRetry ?? false}
        isRetryPending={failedRunRetryAction?.isPending ?? false}
        onRetry={failedRunRetryAction?.onRetry ?? (() => {})}
      />
    );
  }

  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <MessageSurface>
        <Paper
          withBorder
          radius="md"
          p="xs"
          bg="var(--mantine-color-body)"
          style={{ maxWidth: rem(680), overflow: "hidden" }}
        >
          <Box className={classes.errorMessageText}>
            <MarkdownContent>{message.content ?? ""}</MarkdownContent>
          </Box>
        </Paper>

        {message.content && (
          <MessageActionRow
            content={message.content}
            createdAt={message.createdAt}
            align="assistant"
          />
        )}
      </MessageSurface>
    </Box>
  );
}

function AssistantToolCallMessage({
  message,
}: {
  message: ChatMessage;
}): React.ReactElement {
  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <Box style={{ maxWidth: "100%", minWidth: 0 }}>
        {message.toolCalls?.map((tc) => (
          <ToolCallCard key={tc.id} toolCall={tc} />
        ))}
        {message.providerToolCalls?.map((tc) => (
          <ProviderToolCallCard key={tc.id} toolCall={tc} />
        ))}
        {message.attachments && message.attachments.length > 0 && (
          <FileAttachmentList files={message.attachments} />
        )}
      </Box>
    </Box>
  );
}

export const MessageBubble = memo(function MessageBubble({
  message,
  dimmed = false,
  editable = false,
  onEdit,
  failedRunRetryAction = null,
}: MessageBubbleProps): React.ReactElement | null {
  const t = useTranslations("chat");

  // tool, system, and completion marker messages hide
  if (
    message.role === "tool" ||
    message.role === "system" ||
    message.role === "turn_complete" ||
    message.role === "run_complete"
  ) {
    return null;
  }

  const hasContent = message.content !== null && message.content !== "";
  const hasToolCalls =
    (message.toolCalls && message.toolCalls.length > 0) ||
    (message.providerToolCalls && message.providerToolCalls.length > 0);
  const hasReasoning = !!message.reasoningSummary;
  const hasAttachments = message.attachments && message.attachments.length > 0;

  if (message.role === "goal_continuation") {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <GoalControlMessage label={t("goalContinuationIndicator")} />
      </Box>
    );
  }

  if (message.role === "goal_updated") {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <GoalControlMessage label={t("goalUpdatedIndicator")} />
      </Box>
    );
  }

  if (message.role === "skill_loaded") {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <SkillLoadedControlMessage message={message} />
      </Box>
    );
  }

  if (message.role === "interrupted") {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <InterruptedControlMessage />
      </Box>
    );
  }

  if (message.role === "goal_briefing") {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <GoalBriefingCard message={message} />
      </Box>
    );
  }

  // empty message guard: displayto content if nothing exists hide
  if (
    !hasContent &&
    !hasToolCalls &&
    !hasAttachments &&
    message.status !== "partial" &&
    !hasReasoning
  ) {
    return null;
  }

  if (hasToolCalls) {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <AssistantToolCallMessage message={message} />
      </Box>
    );
  }

  if (message.role === "user") {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <UserTextMessage
          message={message}
          hasContent={hasContent}
          hasReasoning={hasReasoning}
          editable={editable}
          onEdit={onEdit}
        />
      </Box>
    );
  }

  if (message.role === "error") {
    return (
      <Box opacity={dimmed ? 0.45 : 1}>
        <ErrorTextMessage
          message={message}
          failedRunRetryAction={failedRunRetryAction}
        />
      </Box>
    );
  }

  return (
    <Box opacity={dimmed ? 0.45 : 1}>
      <AssistantTextMessage
        message={message}
        hasContent={hasContent}
        hasReasoning={hasReasoning}
      />
    </Box>
  );
});
