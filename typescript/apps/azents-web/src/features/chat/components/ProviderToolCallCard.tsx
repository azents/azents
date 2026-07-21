import {
  Box,
  Code,
  Collapse,
  Group,
  rem,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronRight, IconSearch, IconTool } from "@tabler/icons-react";
import { useState } from "react";
import {
  activityDetailScrollbarSize,
  activityRowBorder,
  activityRowChevronSize,
  activityRowDetailInset,
  activityRowIconSize,
  activityRowSummarySize,
  activityRowVerticalPadding,
} from "./activityRowPresentation";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import { FileAttachmentList } from "./FileAttachmentList";
import {
  providerToolActivityLabel,
  providerToolDisplayName,
  providerToolStatusLabel,
} from "./providerToolCallPresentation";
import { providerWebSearchPresentation } from "./providerWebSearchPresentation";
import { ToolCallStatusIcon } from "./ToolCallStatusIcon";
import type { ProviderToolCall } from "../types";
import type { ReactElement } from "react";

interface ProviderToolCallCardProps {
  toolCall: ProviderToolCall;
  hiddenAttachmentUris?: readonly string[];
}

function RawProviderToolDetails({
  toolCall,
}: {
  toolCall: ProviderToolCall;
}): ReactElement | null {
  const hasArguments = toolCall.arguments.trim().length > 0;
  const hasOutput = (toolCall.output?.trim().length ?? 0) > 0;
  if (!hasArguments && !hasOutput) {
    return null;
  }
  return (
    <Stack gap="sm">
      {hasArguments ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            Arguments
          </Text>
          <ScrollArea.Autosize
            mah={rem(240)}
            scrollbarSize={activityDetailScrollbarSize}
          >
            <Code block>{toolCall.arguments}</Code>
          </ScrollArea.Autosize>
        </Box>
      ) : null}
      {hasOutput ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            Output
          </Text>
          <ScrollArea.Autosize
            mah={rem(240)}
            scrollbarSize={activityDetailScrollbarSize}
          >
            <Code block>{toolCall.output}</Code>
          </ScrollArea.Autosize>
        </Box>
      ) : null}
    </Stack>
  );
}

export function ProviderToolCallCard({
  toolCall,
  hiddenAttachmentUris = [],
}: ProviderToolCallCardProps): ReactElement {
  const [opened, setOpened] = useState(false);
  const displayName = providerToolDisplayName(toolCall.name);
  const activityLabel = providerToolActivityLabel(toolCall);
  const webSearch = providerWebSearchPresentation(toolCall);
  const visibleAttachments = (toolCall.attachments ?? []).filter(
    (attachment) => !hiddenAttachmentUris.includes(attachment.uri),
  );
  const showAttachmentsDirectly =
    toolCall.name === "image_generation" && visibleAttachments.length > 0;
  const hasRawDetails =
    toolCall.arguments.trim().length > 0 ||
    (toolCall.output?.trim().length ?? 0) > 0;
  const rawDetails = hasRawDetails ? (
    <RawProviderToolDetails toolCall={toolCall} />
  ) : null;
  const hasDetails =
    webSearch !== null ||
    hasRawDetails ||
    (visibleAttachments.length > 0 && !showAttachmentsDirectly);
  const status = providerToolStatusLabel(toolCall.status);
  const subject = webSearch?.query ?? activityLabel;
  const ariaLabel = [displayName, subject, status].join(" · ");
  const detail = webSearch ? (
    <Stack gap="xs">
      {webSearch.summary !== null ? (
        <Text size="xs" c="dimmed">
          {webSearch.summary}
        </Text>
      ) : null}
      {webSearch.results.map((result) => (
        <Box
          key={result.uri}
          p="xs"
          style={{ border: activityRowBorder, borderRadius: rem(4) }}
        >
          <Stack gap={rem(2)}>
            <Text size="sm" c="dimmed" fw={500} lineClamp={1}>
              {result.title}
            </Text>
            <Text size="xs" c="dimmed" ff="monospace" truncate>
              {result.uri}
            </Text>
            {result.excerpt !== null ? (
              <Text size="xs" c="dimmed" lineClamp={2}>
                {result.excerpt}
              </Text>
            ) : null}
          </Stack>
        </Box>
      ))}
    </Stack>
  ) : (
    rawDetails
  );

  return (
    <>
      <Box
        py={activityRowVerticalPadding}
        data-provider-tool-name={toolCall.name}
        data-provider-tool-status={toolCall.status}
      >
        <UnstyledButton
          w="100%"
          onClick={() => setOpened((value) => !value)}
          aria-expanded={opened}
          aria-label={ariaLabel}
          disabled={!hasDetails}
        >
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <IconChevronRight
              aria-hidden="true"
              size={activityRowChevronSize}
              color="var(--mantine-color-dimmed)"
              style={{
                flexShrink: 0,
                marginTop: rem(2),
                opacity: hasDetails ? 1 : 0,
                transform: opened ? "rotate(90deg)" : "none",
                transition: chatChevronTransition,
              }}
            />
            <Box c="dimmed" style={{ flexShrink: 0, marginTop: rem(1) }}>
              {webSearch !== null ? (
                <IconSearch size={activityRowIconSize} />
              ) : (
                <IconTool size={activityRowIconSize} />
              )}
            </Box>
            <Group gap={rem(6)} flex={1} miw={0} wrap="nowrap">
              <Text
                size={activityRowSummarySize}
                c="dimmed"
                fw={500}
                style={{ flexShrink: 0 }}
              >
                {displayName}
              </Text>
              <Text
                size={activityRowSummarySize}
                c="dimmed"
                truncate
                flex={1}
                miw={0}
              >
                {subject}
              </Text>
            </Group>
            <ToolCallStatusIcon label={status} status={toolCall.status} />
          </Group>
        </UnstyledButton>
        {detail !== null ? (
          <Collapse
            expanded={opened}
            keepMounted={false}
            {...chatCollapseTransitionProps}
          >
            <Box pl={activityRowDetailInset} pr="xs" pt="xs">
              {detail}
            </Box>
          </Collapse>
        ) : null}
      </Box>
      {showAttachmentsDirectly ? (
        <FileAttachmentList files={visibleAttachments} />
      ) : null}
    </>
  );
}
