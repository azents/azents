"use client";

import {
  Accordion,
  ActionIcon,
  Badge,
  Box,
  Code,
  Group,
  Loader,
  Modal,
  rem,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconChevronRight,
  IconCircleOff,
  IconDots,
  IconFileText,
  IconPencil,
  IconPlayerStop,
  IconSearch,
  IconTerminal2,
  IconTool,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { Component, useState } from "react";
import { knownToolPresentation } from "../knownToolPresentation";
import { FileAttachmentList } from "./FileAttachmentList";
import type { KnownToolPresentation } from "../knownToolPresentation";
import type { ActiveToolCall } from "../types";
import type { ReactElement, ReactNode } from "react";

interface ToolCallCardProps {
  toolCall: ActiveToolCall;
  hiddenAttachmentUris?: readonly string[];
}

interface SpecializedToolCallBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
  resetKey: string;
}

interface SpecializedToolCallBoundaryState {
  failed: boolean;
}

type ToolCallTranslations = ReturnType<typeof useTranslations<"chat.toolCall">>;

class SpecializedToolCallBoundary extends Component<
  SpecializedToolCallBoundaryProps,
  SpecializedToolCallBoundaryState
> {
  public state: SpecializedToolCallBoundaryState = { failed: false };

  public static getDerivedStateFromError(): SpecializedToolCallBoundaryState {
    return { failed: true };
  }

  public componentDidUpdate(
    previousProps: SpecializedToolCallBoundaryProps,
  ): void {
    if (this.state.failed && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  public render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Format JSON string. Return original when parsing fails. */
function formatJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function toolCallBadgeColor(status: ActiveToolCall["status"]): string {
  switch (status) {
    case "preparing":
    case "running":
      return "blue";
    case "completed":
      return "green";
    case "failed":
      return "red";
    case "cancelled":
    case "interrupted":
      return "gray";
  }
}

function toolCallStatusIcon(status: ActiveToolCall["status"]): ReactElement {
  switch (status) {
    case "running":
      return <Loader size={rem(16)} />;
    case "failed":
      return <IconAlertTriangle size={rem(16)} />;
    case "cancelled":
      return <IconCircleOff size={rem(16)} />;
    case "interrupted":
      return <IconPlayerStop size={rem(16)} />;
    case "preparing":
    case "completed":
      return <IconTool size={rem(16)} />;
  }
}

function presentationIcon(presentation: KnownToolPresentation): ReactElement {
  switch (presentation.action) {
    case "search":
    case "list":
      return <IconSearch size={rem(14)} />;
    case "edit":
    case "patch":
      return <IconPencil size={rem(14)} />;
    case "command":
    case "process":
      return <IconTerminal2 size={rem(14)} />;
    case "read":
    case "write":
    case "delete":
      return <IconFileText size={rem(14)} />;
  }
}

function genericVisibleAttachments(
  toolCall: ActiveToolCall,
  hiddenAttachmentUris: readonly string[],
): NonNullable<ActiveToolCall["attachments"]> {
  return (toolCall.attachments ?? []).filter(
    (attachment) => !hiddenAttachmentUris.includes(attachment.uri),
  );
}

function actionLabel(
  action: KnownToolPresentation["action"],
  t: ToolCallTranslations,
): string {
  switch (action) {
    case "read":
      return t("action.read");
    case "search":
      return t("action.search");
    case "list":
      return t("action.list");
    case "write":
      return t("action.write");
    case "edit":
      return t("action.edit");
    case "patch":
      return t("action.patch");
    case "delete":
      return t("action.delete");
    case "command":
      return t("action.command");
    case "process":
      return t("action.process");
  }
}

function presentationQualifier(
  presentation: KnownToolPresentation,
  t: ToolCallTranslations,
): string | null {
  if (presentation.qualifier === null) {
    return null;
  }
  switch (presentation.action) {
    case "read":
      return t("fromCharacter", { offset: presentation.qualifier });
    case "patch":
      return t("filesChanged", { count: presentation.qualifier });
    case "command":
    case "process":
      return t("exitCode", { code: presentation.qualifier });
    case "search":
    case "list":
    case "write":
    case "edit":
    case "delete":
      return null;
  }
}

function presentationDetail(
  presentation: KnownToolPresentation,
  t: ToolCallTranslations,
): ReactElement | null {
  if (presentation.detail === null) {
    return null;
  }
  switch (presentation.detail.type) {
    case "output":
      return (
        <ScrollArea.Autosize mah={rem(240)}>
          <Code block>{presentation.detail.output}</Code>
        </ScrollArea.Autosize>
      );
    case "patch":
      return (
        <Stack gap={rem(4)}>
          {presentation.detail.changes.map((change) => (
            <Text
              key={`${change.action}:${change.path}`}
              size="xs"
              ff="monospace"
            >
              {t(`changeAction.${change.action}`)} · {change.path}
            </Text>
          ))}
        </Stack>
      );
    case "process":
      return (
        <Stack gap="xs">
          {presentation.detail.truncated ? (
            <Text size="xs" c="dimmed">
              {t("outputTruncated")}
            </Text>
          ) : null}
          {presentation.detail.output.length > 0 ? (
            <ScrollArea.Autosize mah={rem(240)}>
              <Code block>{presentation.detail.output}</Code>
            </ScrollArea.Autosize>
          ) : null}
        </Stack>
      );
  }
}

function RawPayloadContent({
  argumentsText,
  formatJsonValues = true,
  outputText,
}: {
  argumentsText: string;
  formatJsonValues?: boolean;
  outputText: string;
}): ReactElement {
  const t = useTranslations("chat.toolCall");
  const rawText = (value: string): string =>
    formatJsonValues ? formatJson(value) : value;
  return (
    <Stack gap="sm">
      {argumentsText.length > 0 ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("arguments")}
          </Text>
          <ScrollArea.Autosize mah={rem(240)}>
            <Code block>{rawText(argumentsText)}</Code>
          </ScrollArea.Autosize>
        </Box>
      ) : null}
      {outputText.length > 0 ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("result")}
          </Text>
          <ScrollArea.Autosize mah={rem(240)}>
            <Code block>{rawText(outputText)}</Code>
          </ScrollArea.Autosize>
        </Box>
      ) : null}
    </Stack>
  );
}

function GenericToolCallCard({
  toolCall,
  hiddenAttachmentUris,
}: Required<ToolCallCardProps>): ReactElement {
  const t = useTranslations("chat.toolCall");
  const [openedToolCallId, setOpenedToolCallId] = useState<string | null>(null);
  const isPreparing = toolCall.status === "preparing";
  const isOpened = openedToolCallId === toolCall.id;
  const visibleAttachments = genericVisibleAttachments(
    toolCall,
    hiddenAttachmentUris,
  );

  if (isPreparing) {
    return (
      <Box py="xs">
        <Group gap="xs" wrap="nowrap">
          <Loader size="sm" />
          <Text size="sm" fw={500} c="dimmed">
            {t("preparing")}
          </Text>
        </Group>
      </Box>
    );
  }

  return (
    <>
      <Accordion
        variant="contained"
        my="xs"
        value={openedToolCallId}
        onChange={setOpenedToolCallId}
        disableChevronRotation
        chevron={
          <IconChevronRight
            size={rem(16)}
            style={{
              transform: isOpened ? "rotate(90deg)" : "rotate(0deg)",
              transition: "transform 120ms ease",
            }}
          />
        }
      >
        <Accordion.Item value={toolCall.id}>
          <Accordion.Control icon={toolCallStatusIcon(toolCall.status)}>
            <Group gap="xs">
              <Text size="sm" fw={500}>
                {toolCall.name}
              </Text>
              <Badge
                size="xs"
                variant="light"
                color={toolCallBadgeColor(toolCall.status)}
              >
                {t(toolCall.status)}
              </Badge>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <RawPayloadContent
              argumentsText={toolCall.arguments}
              outputText={toolCall.result ?? ""}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
      {visibleAttachments.length > 0 ? (
        <FileAttachmentList files={visibleAttachments} />
      ) : null}
    </>
  );
}

function SpecializedToolCallCard({
  toolCall,
  presentation,
  hiddenAttachmentUris,
}: {
  toolCall: ActiveToolCall;
  presentation: KnownToolPresentation;
  hiddenAttachmentUris: readonly string[];
}): ReactElement {
  const t = useTranslations("chat.toolCall");
  const [opened, setOpened] = useState(false);
  const [rawOpened, setRawOpened] = useState(false);
  const detail = presentationDetail(presentation, t);
  const qualifier = presentationQualifier(presentation, t);
  const visibleAttachments = genericVisibleAttachments(
    toolCall,
    hiddenAttachmentUris,
  );
  const action = actionLabel(presentation.action, t);
  const status = t(toolCall.status);
  const hasRawData =
    toolCall.arguments.length > 0 || (toolCall.result?.length ?? 0) > 0;
  const ariaLabel = [
    action,
    presentation.subject ?? "",
    qualifier ?? "",
    status,
  ]
    .filter((value) => value.length > 0)
    .join(" · ");
  const summary = (
    <Group gap="xs" wrap="nowrap" align="flex-start">
      <IconChevronRight
        aria-hidden="true"
        size={rem(14)}
        color="var(--mantine-color-dimmed)"
        style={{
          flexShrink: 0,
          marginTop: rem(3),
          opacity: detail === null ? 0 : 1,
          transform: opened ? "rotate(90deg)" : "none",
          transition: "transform 120ms ease",
        }}
      />
      <ThemeIcon
        size="sm"
        radius="xl"
        variant="light"
        color={toolCall.status === "failed" ? "red" : "gray"}
        style={{ flexShrink: 0 }}
      >
        {presentationIcon(presentation)}
      </ThemeIcon>
      <Group gap={rem(6)} flex={1} miw={0} wrap="wrap">
        <Text size="sm" fw={600}>
          {action}
        </Text>
        {presentation.subject !== null ? (
          <Text size="sm" c="dimmed" ff="monospace" truncate miw={0}>
            {presentation.subject}
          </Text>
        ) : null}
        {qualifier !== null ? (
          <Text size="xs" c="dimmed">
            {qualifier}
          </Text>
        ) : null}
      </Group>
      <Badge
        size="xs"
        variant="light"
        color={toolCallBadgeColor(toolCall.status)}
        style={{ flexShrink: 0 }}
      >
        {status}
      </Badge>
    </Group>
  );

  return (
    <>
      <Box py="xs">
        <Group gap={rem(4)} wrap="nowrap" align="flex-start">
          {detail === null ? (
            <Box flex={1} miw={0} aria-label={ariaLabel}>
              {summary}
            </Box>
          ) : (
            <UnstyledButton
              flex={1}
              miw={0}
              onClick={() => setOpened((value) => !value)}
              aria-expanded={opened}
              aria-label={ariaLabel}
            >
              {summary}
            </UnstyledButton>
          )}
          {hasRawData ? (
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              aria-label={t("viewRawDataFor", { action })}
              onClick={() => setRawOpened(true)}
            >
              <IconDots size={rem(15)} />
            </ActionIcon>
          ) : null}
        </Group>
        {opened && detail !== null ? (
          <Box pl={rem(54)} pr="xs" pt="xs">
            {detail}
          </Box>
        ) : null}
      </Box>
      {visibleAttachments.length > 0 ? (
        <FileAttachmentList files={visibleAttachments} />
      ) : null}
      {hasRawData ? (
        <Modal
          opened={rawOpened}
          onClose={() => setRawOpened(false)}
          title={t("rawData")}
          centered
          size="lg"
        >
          <RawPayloadContent
            argumentsText={toolCall.arguments}
            formatJsonValues={false}
            outputText={toolCall.result ?? ""}
          />
        </Modal>
      ) : null}
    </>
  );
}

export function ToolCallCard({
  toolCall,
  hiddenAttachmentUris = [],
}: ToolCallCardProps): ReactElement {
  const result = knownToolPresentation(toolCall);
  const generic = (
    <GenericToolCallCard
      toolCall={toolCall}
      hiddenAttachmentUris={hiddenAttachmentUris}
    />
  );
  if (result.type === "generic") {
    return generic;
  }
  return (
    <SpecializedToolCallBoundary
      resetKey={`${toolCall.id}:${toolCall.status}:${toolCall.result ?? ""}`}
      fallback={generic}
    >
      <SpecializedToolCallCard
        toolCall={toolCall}
        presentation={result.presentation}
        hiddenAttachmentUris={hiddenAttachmentUris}
      />
    </SpecializedToolCallBoundary>
  );
}
