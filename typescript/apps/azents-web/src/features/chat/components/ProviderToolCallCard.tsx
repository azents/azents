import {
  Box,
  Code,
  Group,
  Loader,
  rem,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronRight, IconSearch, IconTool } from "@tabler/icons-react";
import { useState } from "react";
import { FileAttachmentList } from "./FileAttachmentList";
import {
  providerToolActivityLabel,
  providerToolDisplayName,
  providerToolStatusLabel,
} from "./providerToolCallPresentation";
import { providerWebSearchPresentation } from "./providerWebSearchPresentation";
import type { ProviderToolCall } from "../types";
import type { ReactElement } from "react";

interface ProviderToolCallCardProps {
  toolCall: ProviderToolCall;
  hiddenAttachmentUris?: readonly string[];
}

const flatRowBorder = "1px solid var(--mantine-color-default-border)";

function statusColor(status: ProviderToolCall["status"]): string {
  switch (status) {
    case "running":
      return "blue";
    case "failed":
      return "red";
    case "completed":
    case "unknown":
      return "dimmed";
  }
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
          <ScrollArea.Autosize mah={rem(240)}>
            <Code block>{toolCall.arguments}</Code>
          </ScrollArea.Autosize>
        </Box>
      ) : null}
      {hasOutput ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            Output
          </Text>
          <ScrollArea.Autosize mah={rem(240)}>
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
  const color = statusColor(toolCall.status);
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
          style={{ border: flatRowBorder, borderRadius: rem(4) }}
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
        py="xs"
        style={{ borderBottom: flatRowBorder }}
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
              size={rem(14)}
              color="var(--mantine-color-dimmed)"
              style={{
                flexShrink: 0,
                marginTop: rem(2),
                opacity: hasDetails ? 1 : 0,
                transform: opened ? "rotate(90deg)" : "none",
                transition: "transform 120ms ease",
              }}
            />
            <Box c={color} style={{ flexShrink: 0, marginTop: rem(1) }}>
              {toolCall.status === "running" ? (
                <Loader size={rem(14)} />
              ) : webSearch !== null ? (
                <IconSearch size={rem(14)} />
              ) : (
                <IconTool size={rem(14)} />
              )}
            </Box>
            <Group gap={rem(6)} flex={1} miw={0} wrap="nowrap">
              <Text size="sm" c="dimmed" fw={500} style={{ flexShrink: 0 }}>
                {displayName}
              </Text>
              <Text size="sm" c="dimmed" truncate flex={1} miw={0}>
                {subject}
              </Text>
            </Group>
            <Text size="xs" c={color} style={{ flexShrink: 0 }}>
              {status}
            </Text>
          </Group>
        </UnstyledButton>
        {opened && detail !== null ? (
          <Box pl={rem(54)} pr="xs" pt="xs">
            {detail}
          </Box>
        ) : null}
      </Box>
      {showAttachmentsDirectly ? (
        <FileAttachmentList files={visibleAttachments} />
      ) : null}
    </>
  );
}
