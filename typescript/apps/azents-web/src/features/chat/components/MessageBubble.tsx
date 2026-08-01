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
  Group,
  Paper,
  rem,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconCheck,
  IconClock,
  IconMessageCircle,
  IconPencil,
  IconTargetArrow,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import { memo } from "react";
import { continuationPresentation } from "../continuationPresentation";
import { externalChannelMessagePresentation } from "../externalChannelMessage";
import {
  type CurrentWorkspaceProfile,
  humanSenderPresentation,
} from "../senderPresentation";
import { AgentMessageDisclosure } from "./AgentMessageDisclosure";
import inlineControlClasses from "./ChatInlineControl.module.css";
import { ExternalChannelMessage } from "./ExternalChannelMessage";
import { FileAttachmentList } from "./FileAttachmentList";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import { MarkdownContent } from "./MarkdownContent";
import { MessageActionRow } from "./MessageActionRow";
import classes from "./MessageBubble.module.css";
import { MessageMetadataSurface } from "./MessageMetadataFooter";
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
  currentWorkspaceProfile?: CurrentWorkspaceProfile | null;
  dimmed?: boolean;
  opacity?: number;
  editable?: boolean;
  onEdit?: () => void;
  failedRunRetryAction?: FailedRunRetryAction | null;
  additionalActions?: React.ReactNode;
}

interface TextMessageProps {
  message: ChatMessage;
  hasContent: boolean;
  senderLabel: string;
}

type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

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

function TextMessageContent({
  message,
}: {
  message: ChatMessage;
}): React.ReactElement {
  return (
    <>
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
    </>
  );
}

function UserTextMessage({
  message,
  hasContent,
  senderLabel,
  editable = false,
  onEdit,
  additionalActions = null,
}: TextMessageProps & {
  editable?: boolean;
  onEdit?: () => void;
  additionalActions?: React.ReactNode;
}): React.ReactElement {
  const t = useTranslations("chat");
  const editAction =
    editable && onEdit ? (
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
    ) : null;

  if (message.action) {
    return (
      <MessageMetadataSurface>
        <Text size="xs" c="dimmed" ta="right" mb={rem(4)}>
          {senderLabel}
        </Text>
        <InputBufferBubbleFrame
          content={message.content ?? ""}
          action={message.action}
          attachments={[]}
          attachmentFiles={message.attachments}
          opacity={1}
          actions={
            message.status !== "partial" &&
            (message.content !== null || message.inferenceProfile) ? (
              <MessageActionRow
                content={message.content}
                createdAt={message.createdAt}
                align="user"
                inferenceProfile={message.inferenceProfile}
                additionalActions={
                  <>
                    {additionalActions}
                    {editAction}
                  </>
                }
              />
            ) : null
          }
        />
      </MessageMetadataSurface>
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
        <MessageMetadataSurface>
          <Text size="xs" c="dimmed" ta="right" mb={rem(4)}>
            {senderLabel}
          </Text>
          {message.attachments && message.attachments.length > 0 && (
            <FileAttachmentList
              files={message.attachments}
              presentation="compact"
            />
          )}

          {hasContent && (
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
              <TextMessageContent message={message} />
            </Paper>
          )}

          {message.status !== "partial" &&
            (message.content !== null || message.inferenceProfile) && (
              <MessageActionRow
                content={message.content}
                createdAt={message.createdAt}
                align="user"
                inferenceProfile={message.inferenceProfile}
                additionalActions={
                  <>
                    {additionalActions}
                    {editAction}
                  </>
                }
              />
            )}
        </MessageMetadataSurface>
      </Box>
    </Group>
  );
}

function isAgentMailboxMessage(message: ChatMessage): boolean {
  return message.metadata?.source === "agent_mailbox";
}

function agentNameFromPath(path: string): string {
  const segments = path.split("/").filter(Boolean);
  return segments.at(-1) ?? path;
}

function AgentMailboxMessage({
  message,
  additionalActions = null,
}: {
  message: ChatMessage;
  additionalActions?: React.ReactNode;
}): React.ReactElement {
  const t = useTranslations("chat");
  const sourcePath = message.metadata?.source_path || "/root";
  const sourceName = agentNameFromPath(sourcePath);

  return (
    <AgentMessageDisclosure
      title={t("agentMessage.title", { name: sourceName })}
      titleTooltip={sourcePath}
      content={message.content ?? ""}
      actions={
        additionalActions ? (
          <MessageActionRow
            content={message.content}
            createdAt={message.createdAt}
            align="user"
            inferenceProfile={message.inferenceProfile}
            additionalActions={additionalActions}
          />
        ) : null
      }
    />
  );
}

function AssistantTextMessage({
  message,
  hasContent,
}: Pick<TextMessageProps, "message" | "hasContent">): React.ReactElement {
  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <Box style={{ maxWidth: "100%", minWidth: 0, overflowWrap: "anywhere" }}>
        <MessageMetadataSurface>
          {hasContent && <TextMessageContent message={message} />}

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
        </MessageMetadataSurface>
      </Box>
    </Box>
  );
}

function InlineControlMessage({
  icon,
  label,
  actions = null,
}: {
  icon: React.ReactNode;
  label: string;
  actions?: React.ReactNode;
}): React.ReactElement {
  return (
    <Box mb="md">
      <Group
        gap={rem(6)}
        c="dimmed"
        wrap="nowrap"
        className={inlineControlClasses.root}
      >
        {icon}
        <Text size="xs" className={inlineControlClasses.label}>
          {label}
        </Text>
      </Group>
      {actions}
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
            <Box style={{ overflowWrap: "anywhere" }}>
              <MarkdownContent>{objective}</MarkdownContent>
            </Box>
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
      <MessageMetadataSurface>
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
      </MessageMetadataSurface>
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
  currentWorkspaceProfile = null,
  dimmed = false,
  opacity,
  editable = false,
  onEdit,
  failedRunRetryAction = null,
  additionalActions = null,
}: MessageBubbleProps): React.ReactElement | null {
  const t = useTranslations("chat");
  const messageOpacity = opacity ?? (dimmed ? 0.45 : 1);

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
  const hasAttachments = message.attachments && message.attachments.length > 0;
  const externalChannelSource = externalChannelMessagePresentation(message);
  const sender = humanSenderPresentation(
    message.senderUserId ?? null,
    currentWorkspaceProfile,
  );
  const senderLabel =
    sender.type === "AVAILABLE" ? sender.name : t("senderUnavailable");

  if (
    message.role === "goal_continuation" ||
    message.role === "external_channel_continuation"
  ) {
    const continuation = continuationPresentation(message);
    return (
      <Box opacity={messageOpacity}>
        <InlineControlMessage
          icon={
            continuation.icon === "channel" ? (
              <IconMessageCircle aria-hidden="true" size={14} stroke={1.8} />
            ) : (
              <IconTargetArrow aria-hidden="true" size={14} stroke={1.8} />
            )
          }
          label={t(continuation.labelKey)}
          actions={
            additionalActions ? (
              <MessageActionRow
                content={message.content}
                createdAt={message.createdAt}
                align="user"
                inferenceProfile={message.inferenceProfile}
                additionalActions={additionalActions}
              />
            ) : null
          }
        />
      </Box>
    );
  }

  if (message.role === "goal_updated") {
    return (
      <Box opacity={messageOpacity}>
        <InlineControlMessage
          icon={<IconTargetArrow aria-hidden="true" size={14} stroke={1.8} />}
          label={t("goalUpdatedIndicator")}
        />
      </Box>
    );
  }

  if (message.role === "interrupted") {
    return (
      <Box opacity={messageOpacity}>
        <InterruptedControlMessage />
      </Box>
    );
  }

  if (message.role === "goal_briefing") {
    return (
      <Box opacity={messageOpacity}>
        <GoalBriefingCard message={message} />
      </Box>
    );
  }

  if (externalChannelSource !== null) {
    return (
      <Box opacity={messageOpacity}>
        <ExternalChannelMessage
          source={externalChannelSource}
          partial={message.status === "partial"}
          actions={
            additionalActions ? (
              <MessageActionRow
                content={message.content}
                createdAt={message.createdAt}
                align="user"
                inferenceProfile={message.inferenceProfile}
                additionalActions={additionalActions}
              />
            ) : null
          }
        />
      </Box>
    );
  }

  // empty message guard: displayto content if nothing exists hide
  if (!hasContent && !hasToolCalls && !hasAttachments) {
    return null;
  }

  if (hasToolCalls) {
    return (
      <Box opacity={messageOpacity}>
        <AssistantToolCallMessage message={message} />
      </Box>
    );
  }

  if (message.role === "user" && isAgentMailboxMessage(message)) {
    return (
      <Box opacity={messageOpacity}>
        <AgentMailboxMessage
          message={message}
          additionalActions={additionalActions}
        />
      </Box>
    );
  }

  if (message.role === "user") {
    return (
      <Box opacity={messageOpacity}>
        <UserTextMessage
          message={message}
          hasContent={hasContent}
          senderLabel={senderLabel}
          editable={editable}
          onEdit={onEdit}
          additionalActions={additionalActions}
        />
      </Box>
    );
  }

  if (message.role === "error") {
    return (
      <Box opacity={messageOpacity}>
        <ErrorTextMessage
          message={message}
          failedRunRetryAction={failedRunRetryAction}
        />
      </Box>
    );
  }

  return (
    <Box opacity={messageOpacity}>
      <AssistantTextMessage message={message} hasContent={hasContent} />
    </Box>
  );
});
