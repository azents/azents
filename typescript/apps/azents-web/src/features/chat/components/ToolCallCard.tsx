"use client";

import {
  ActionIcon,
  Box,
  Code,
  Collapse,
  Group,
  Modal,
  rem,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import {
  IconChevronRight,
  IconDots,
  IconFileExport,
  IconFileText,
  IconPencil,
  IconSearch,
  IconTerminal2,
  IconTool,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { Component, useState } from "react";
import { knownToolPresentation } from "../knownToolPresentation";
import {
  activityDetailScrollbarSize,
  activityRowBorder,
  activityRowChevronSize,
  activityRowDetailInset,
  activityRowIconSize,
  activityRowSummarySize,
  activityRowVerticalPadding,
} from "./activityRowPresentation";
import inlineControlClasses from "./ChatInlineControl.module.css";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import { FileAttachmentList } from "./FileAttachmentList";
import { ToolCallStatusIcon } from "./ToolCallStatusIcon";
import type { KnownToolPresentation } from "../knownToolPresentation";
import type { ActiveToolCall } from "../types";
import type {
  V4APatchFile,
  V4APatchHunk,
  V4APatchLine,
} from "../v4aPatchPresentation";
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

function presentationIcon(presentation: KnownToolPresentation): ReactElement {
  switch (presentation.action) {
    case "search":
    case "list":
      return <IconSearch size={activityRowIconSize} />;
    case "edit":
    case "patch":
      return <IconPencil size={activityRowIconSize} />;
    case "command":
    case "process":
      return <IconTerminal2 size={activityRowIconSize} />;
    case "read":
    case "write":
    case "delete":
      return <IconFileText size={activityRowIconSize} />;
    case "present":
      return <IconFileExport size={activityRowIconSize} />;
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
    case "present":
      return t("action.present");
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
    case "present":
      return null;
  }
}

function patchLinePrefix(line: V4APatchLine): string {
  switch (line.type) {
    case "add":
      return "+";
    case "remove":
      return "−";
    case "context":
      return " ";
  }
}

function patchLineBackground(line: V4APatchLine): string {
  switch (line.type) {
    case "add":
      return "var(--mantine-color-green-light)";
    case "remove":
      return "var(--mantine-color-red-light)";
    case "context":
      return "transparent";
  }
}

function patchLineColor(line: V4APatchLine): string {
  switch (line.type) {
    case "add":
      return "var(--mantine-color-green-light-color)";
    case "remove":
      return "var(--mantine-color-red-light-color)";
    case "context":
      return "dimmed";
  }
}

function patchFileActionColor(file: V4APatchFile): string {
  switch (file.type) {
    case "add":
      return "var(--mantine-color-green-light-color)";
    case "delete":
      return "var(--mantine-color-red-light-color)";
    case "update":
      return "dimmed";
  }
}

function PatchLine({ line }: { line: V4APatchLine }): ReactElement {
  return (
    <Group
      gap="xs"
      wrap="nowrap"
      align="flex-start"
      px="xs"
      bg={patchLineBackground(line)}
    >
      <Text
        aria-hidden="true"
        c={patchLineColor(line)}
        ff="monospace"
        size="xs"
        w={rem(12)}
      >
        {patchLinePrefix(line)}
      </Text>
      <Text
        component="code"
        c={patchLineColor(line)}
        ff="monospace"
        size="xs"
        style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}
      >
        {line.content.length > 0 ? line.content : " "}
      </Text>
    </Group>
  );
}

function PatchHunk({ hunk }: { hunk: V4APatchHunk }): ReactElement {
  return (
    <Stack gap={0}>
      {hunk.context !== null ? (
        <Text px="xs" py={rem(2)} size="xs" c="dimmed" ff="monospace">
          {hunk.context}
        </Text>
      ) : null}
      {hunk.lines.map((line, index) => (
        <PatchLine key={`${line.type}:${index}`} line={line} />
      ))}
    </Stack>
  );
}

function PatchFile({ file }: { file: V4APatchFile }): ReactElement {
  const t = useTranslations("chat.toolCall");
  const destination = file.type === "update" ? file.moveTo : null;

  return (
    <Box
      style={{
        border: activityRowBorder,
        borderRadius: "var(--mantine-radius-sm)",
        overflow: "hidden",
      }}
    >
      <Group gap="xs" wrap="nowrap" px="xs" py={rem(6)} bg="default">
        <Text size="xs" c={patchFileActionColor(file)} fw={600}>
          {t(`changeAction.${file.type}`)}
        </Text>
        <Text
          size="xs"
          ff="monospace"
          flex={1}
          miw={0}
          style={{ overflowWrap: "anywhere", whiteSpace: "normal" }}
        >
          {file.path}
        </Text>
        {destination !== null ? (
          <Text
            size="xs"
            c="dimmed"
            ff="monospace"
            miw={0}
            style={{ overflowWrap: "anywhere", whiteSpace: "normal" }}
          >
            → {destination}
          </Text>
        ) : null}
      </Group>
      {file.type === "add" ? (
        <Stack gap={0}>
          {file.lines.map((content, index) => (
            <PatchLine key={`add:${index}`} line={{ type: "add", content }} />
          ))}
        </Stack>
      ) : null}
      {file.type === "update" ? (
        <Stack gap="xs" py="xs">
          {file.hunks.map((hunk, index) => (
            <PatchHunk key={`${hunk.context ?? "root"}:${index}`} hunk={hunk} />
          ))}
        </Stack>
      ) : null}
    </Box>
  );
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
        <ScrollArea.Autosize
          mah={rem(240)}
          scrollbarSize={activityDetailScrollbarSize}
        >
          <Code block>{presentation.detail.output}</Code>
        </ScrollArea.Autosize>
      );
    case "diff":
      return <PatchFile file={presentation.detail.file} />;
    case "patch":
      return (
        <Stack gap="xs">
          {presentation.detail.files.map((file) => (
            <PatchFile key={`${file.type}:${file.path}`} file={file} />
          ))}
        </Stack>
      );
    case "process": {
      const consoleOutput = [
        presentation.detail.command === null
          ? null
          : `$ ${presentation.detail.command}`,
        presentation.detail.output,
      ]
        .filter((value): value is string => value !== null && value.length > 0)
        .join("\n\n");
      return (
        <Stack gap="xs">
          {consoleOutput.length > 0 ? (
            <ScrollArea.Autosize
              mah={rem(240)}
              scrollbarSize={activityDetailScrollbarSize}
            >
              <Code block>{consoleOutput}</Code>
            </ScrollArea.Autosize>
          ) : null}
          {presentation.detail.truncated ? (
            <Text size="xs" c="dimmed">
              {t("outputTruncated")}
            </Text>
          ) : null}
        </Stack>
      );
    }
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
          <ScrollArea.Autosize
            mah={rem(240)}
            scrollbarSize={activityDetailScrollbarSize}
          >
            <Code block>{rawText(argumentsText)}</Code>
          </ScrollArea.Autosize>
        </Box>
      ) : null}
      {outputText.length > 0 ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("result")}
          </Text>
          <ScrollArea.Autosize
            mah={rem(240)}
            scrollbarSize={activityDetailScrollbarSize}
          >
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
  const [opened, setOpened] = useState(false);
  const visibleAttachments = genericVisibleAttachments(
    toolCall,
    hiddenAttachmentUris,
  );
  const detail =
    toolCall.arguments.length > 0 || (toolCall.result?.length ?? 0) > 0 ? (
      <RawPayloadContent
        argumentsText={toolCall.arguments}
        outputText={toolCall.result ?? ""}
      />
    ) : null;
  const status = t(toolCall.status);
  const ariaLabel = [toolCall.name, t("genericDetails"), status].join(" · ");

  return (
    <>
      <Box py={activityRowVerticalPadding}>
        <UnstyledButton
          w="100%"
          onClick={() => setOpened((value) => !value)}
          aria-expanded={opened}
          aria-label={ariaLabel}
          disabled={detail === null}
        >
          <Group gap="xs" wrap="nowrap" className={inlineControlClasses.root}>
            <IconChevronRight
              aria-hidden="true"
              size={activityRowChevronSize}
              color="var(--mantine-color-dimmed)"
              style={{
                flexShrink: 0,
                marginTop: rem(2),
                opacity: detail === null ? 0 : 1,
                transform: opened ? "rotate(90deg)" : "none",
                transition: chatChevronTransition,
              }}
            />
            <Box c="dimmed" style={{ display: "inline-flex", flexShrink: 0 }}>
              <IconTool size={activityRowIconSize} />
            </Box>
            <Group gap={rem(6)} flex={1} miw={0} wrap="nowrap">
              <Text
                size={activityRowSummarySize}
                c="dimmed"
                fw={500}
                className={inlineControlClasses.label}
                style={{ flexShrink: 0 }}
              >
                {toolCall.name}
              </Text>
              <Text
                size={activityRowSummarySize}
                c="dimmed"
                truncate
                miw={0}
                className={inlineControlClasses.label}
              >
                {t("genericDetails")}
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
    <Group gap="xs" wrap="nowrap" className={inlineControlClasses.root}>
      <IconChevronRight
        aria-hidden="true"
        size={activityRowChevronSize}
        color="var(--mantine-color-dimmed)"
        style={{
          flexShrink: 0,
          marginTop: rem(2),
          opacity: detail === null ? 0 : 1,
          transform: opened ? "rotate(90deg)" : "none",
          transition: chatChevronTransition,
        }}
      />
      <Box
        c="dimmed"
        style={{ display: "inline-flex", flexShrink: 0, marginTop: rem(1) }}
      >
        {presentationIcon(presentation)}
      </Box>
      <Group gap={rem(6)} flex={1} miw={0} wrap="nowrap">
        <Text
          size={activityRowSummarySize}
          c="dimmed"
          fw={500}
          className={inlineControlClasses.label}
          style={{ flexShrink: 0 }}
        >
          {action}
        </Text>
        {presentation.subject !== null ? (
          <Text
            size={activityRowSummarySize}
            c="dimmed"
            truncate
            flex={1}
            miw={0}
            className={inlineControlClasses.label}
          >
            {presentation.subject}
          </Text>
        ) : null}
        {qualifier !== null ? (
          <Text
            size={activityRowSummarySize}
            c="dimmed"
            truncate
            miw={0}
            className={inlineControlClasses.label}
            style={{ flexShrink: 1 }}
          >
            {qualifier}
          </Text>
        ) : null}
      </Group>
      <ToolCallStatusIcon label={status} status={toolCall.status} />
    </Group>
  );

  return (
    <>
      <Box py={activityRowVerticalPadding}>
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
              size={rem(16)}
              variant="subtle"
              color="gray"
              aria-label={t("viewRawDataFor", { action })}
              onClick={() => setRawOpened(true)}
            >
              <IconDots size={activityRowIconSize} />
            </ActionIcon>
          ) : null}
        </Group>
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
