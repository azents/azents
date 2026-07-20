import {
  ActionIcon,
  Badge,
  Box,
  Code,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconChevronDown,
  IconChevronRight,
  IconTool,
} from "@tabler/icons-react";
import { FileAttachmentList } from "./FileAttachmentList";
import {
  providerToolActivityLabel,
  providerToolDisplayName,
  providerToolStatusLabel,
} from "./providerToolCallPresentation";
import type { ProviderToolCall } from "../types";

interface ProviderToolCallCardProps {
  toolCall: ProviderToolCall;
  hiddenAttachmentUris?: readonly string[];
}

function statusColor(status: ProviderToolCall["status"]): string {
  switch (status) {
    case "completed":
      return "green";
    case "failed":
      return "red";
    case "running":
      return "blue";
    case "unknown":
      return "gray";
  }
}

export function ProviderToolCallCard({
  toolCall,
  hiddenAttachmentUris = [],
}: ProviderToolCallCardProps): React.ReactElement {
  const [opened, { toggle }] = useDisclosure(false);
  const displayName = providerToolDisplayName(toolCall.name);
  const activityLabel = providerToolActivityLabel(toolCall);
  const hasArguments = toolCall.arguments.trim().length > 0;
  const hasOutput = (toolCall.output?.trim().length ?? 0) > 0;
  const visibleAttachments = (toolCall.attachments ?? []).filter(
    (attachment) => !hiddenAttachmentUris.includes(attachment.uri),
  );
  const hasAttachments = visibleAttachments.length > 0;
  const showAttachmentsDirectly =
    toolCall.name === "image_generation" && hasAttachments;
  const hasDetails =
    hasArguments || hasOutput || (hasAttachments && !showAttachmentsDirectly);

  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      mb="xs"
      bg="var(--mantine-color-body)"
      data-provider-tool-name={toolCall.name}
      data-provider-tool-status={toolCall.status}
    >
      <Stack gap="xs">
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon size="sm" variant="light" color="gray">
              <IconTool size={14} />
            </ThemeIcon>
            <Box style={{ minWidth: 0 }}>
              <Text size="sm" fw={600} truncate>
                {displayName}
              </Text>
              <Text size="xs" c="dimmed">
                {activityLabel}
              </Text>
            </Box>
          </Group>
          <Group gap="xs" wrap="nowrap">
            {toolCall.status === "running" ? (
              <Loader
                size="xs"
                color="blue"
                aria-label="Provider tool running"
              />
            ) : null}
            <Badge
              size="sm"
              color={statusColor(toolCall.status)}
              variant="light"
            >
              {providerToolStatusLabel(toolCall.status)}
            </Badge>
            {hasDetails ? (
              <ActionIcon
                size="sm"
                variant="subtle"
                onClick={toggle}
                aria-label={opened ? "Hide tool details" : "Show tool details"}
              >
                {opened ? (
                  <IconChevronDown size={14} />
                ) : (
                  <IconChevronRight size={14} />
                )}
              </ActionIcon>
            ) : null}
          </Group>
        </Group>
        {showAttachmentsDirectly ? (
          <FileAttachmentList files={visibleAttachments} />
        ) : null}
        {opened ? (
          <Stack gap="xs">
            {hasArguments ? (
              <Box>
                <Text size="xs" c="dimmed" mb="xs">
                  Arguments
                </Text>
                <Code block>{toolCall.arguments}</Code>
              </Box>
            ) : null}
            {hasOutput ? (
              <Box>
                <Text size="xs" c="dimmed" mb="xs">
                  Output
                </Text>
                <Code block>{toolCall.output}</Code>
              </Box>
            ) : null}
            {hasAttachments && !showAttachmentsDirectly ? (
              <FileAttachmentList files={visibleAttachments} />
            ) : null}
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}
