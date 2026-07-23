import {
  ActionIcon,
  Anchor,
  Box,
  Code,
  Modal,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import { IconDots, IconTool, IconWorld } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ActivityRow } from "./ActivityRow";
import {
  activityDetailScrollAreaProps,
  activityDetailScrollbarSize,
  activityRowBorder,
  activityRowIconSize,
} from "./activityRowPresentation";
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
  showToolName = false,
}: {
  toolCall: ProviderToolCall;
  showToolName?: boolean;
}): ReactElement {
  const t = useTranslations("chat.toolCall");
  const hasArguments = toolCall.arguments.trim().length > 0;
  const hasOutput = (toolCall.output?.trim().length ?? 0) > 0;
  return (
    <Stack gap="sm">
      {showToolName ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("toolName")}
          </Text>
          <Code block>{toolCall.name}</Code>
        </Box>
      ) : null}
      {hasArguments ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("arguments")}
          </Text>
          <ScrollArea.Autosize
            mah={rem(240)}
            scrollbarSize={activityDetailScrollbarSize}
            {...activityDetailScrollAreaProps}
          >
            <Code block>{toolCall.arguments}</Code>
          </ScrollArea.Autosize>
        </Box>
      ) : null}
      {hasOutput ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("result")}
          </Text>
          <ScrollArea.Autosize
            mah={rem(240)}
            scrollbarSize={activityDetailScrollbarSize}
            {...activityDetailScrollAreaProps}
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
  const t = useTranslations("chat.toolCall");
  const [rawOpened, setRawOpened] = useState(false);
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
  const status = providerToolStatusLabel(toolCall.status);
  const subject =
    webSearch !== null && webSearch.queries.length > 0
      ? webSearch.queries.join(" · ")
      : activityLabel;
  const ariaLabel = [displayName, subject, status].join(" · ");
  const webSearchDetail =
    webSearch !== null &&
    (webSearch.queries.length > 0 ||
      webSearch.summary !== null ||
      webSearch.results.length > 0) ? (
      <Stack gap="xs">
        {webSearch.queries.length > 0 ? (
          <Box>
            <Text size="xs" c="dimmed" mb={rem(4)}>
              {t("field.query")}
            </Text>
            <Stack gap={rem(2)}>
              {webSearch.queries.map((query) => (
                <Text
                  key={query}
                  size="xs"
                  style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}
                >
                  {query}
                </Text>
              ))}
            </Stack>
          </Box>
        ) : null}
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
              <Anchor
                href={result.uri}
                target="_blank"
                rel="noreferrer"
                size="sm"
                c="dimmed"
                fw={500}
                lineClamp={1}
              >
                {result.title}
              </Anchor>
              <Text size="xs" c="dimmed" truncate>
                {new URL(result.uri).hostname}
              </Text>
              <Anchor
                href={result.uri}
                target="_blank"
                rel="noreferrer"
                size="xs"
                c="dimmed"
                ff="monospace"
                truncate
              >
                {result.uri}
              </Anchor>
              {result.excerpt !== null ? (
                <Text size="xs" c="dimmed" lineClamp={2}>
                  {result.excerpt}
                </Text>
              ) : null}
            </Stack>
          </Box>
        ))}
      </Stack>
    ) : null;
  const detail =
    webSearchDetail ??
    rawDetails ??
    (visibleAttachments.length > 0 && !showAttachmentsDirectly ? (
      <FileAttachmentList files={visibleAttachments} />
    ) : null);

  return (
    <>
      <Box
        data-provider-tool-name={toolCall.name}
        data-provider-tool-status={toolCall.status}
      >
        <ActivityRow
          action={
            <ActionIcon
              size={rem(16)}
              variant="subtle"
              color="gray"
              aria-label={t("viewRawDataFor", { action: displayName })}
              onClick={() => setRawOpened(true)}
            >
              <IconDots size={activityRowIconSize} />
            </ActionIcon>
          }
          ariaLabel={ariaLabel}
          detail={detail}
          icon={
            webSearch !== null ? (
              <IconWorld size={activityRowIconSize} />
            ) : (
              <IconTool size={activityRowIconSize} />
            )
          }
          primary={displayName}
          status={
            <ToolCallStatusIcon label={status} status={toolCall.status} />
          }
          subject={subject}
        />
      </Box>
      {showAttachmentsDirectly ? (
        <FileAttachmentList files={visibleAttachments} />
      ) : null}
      <Modal
        opened={rawOpened}
        onClose={() => setRawOpened(false)}
        title={t("rawData")}
        centered
        size="lg"
      >
        <RawProviderToolDetails toolCall={toolCall} showToolName />
      </Modal>
    </>
  );
}
