"use client";

import {
  ActionIcon,
  Box,
  Code,
  Group,
  Modal,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconBook,
  IconBrain,
  IconDots,
  IconDownload,
  IconFileExport,
  IconFileText,
  IconPencil,
  IconPhoto,
  IconRobot,
  IconSearch,
  IconSquareCheck,
  IconTargetArrow,
  IconTerminal2,
  IconTool,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { Component, useState } from "react";
import { knownToolPresentation } from "../knownToolPresentation";
import { ActivityRow } from "./ActivityRow";
import {
  activityDetailScrollAreaProps,
  activityDetailScrollbarSize,
  activityRowBorder,
  activityRowIconSize,
} from "./activityRowPresentation";
import { ChatCodeBlock } from "./ChatCodeBlock";
import { FileAttachmentList } from "./FileAttachmentList";
import { SkillContentPanel } from "./SkillContentPanel";
import { ToolCallStatusIcon } from "./ToolCallStatusIcon";
import type {
  KnownToolDetailLabel,
  KnownToolPresentation,
} from "../knownToolPresentation";
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
    case "grep":
    case "glob":
    case "toolSearch":
      return <IconSearch size={activityRowIconSize} />;
    case "edit":
    case "patch":
    case "write":
      return <IconPencil size={activityRowIconSize} />;
    case "command":
    case "process":
      return <IconTerminal2 size={activityRowIconSize} />;
    case "read":
    case "delete":
      return <IconFileText size={activityRowIconSize} />;
    case "present":
      return <IconFileExport size={activityRowIconSize} />;
    case "readImage":
      return <IconPhoto size={activityRowIconSize} />;
    case "importFile":
      return <IconDownload size={activityRowIconSize} />;
    case "saveMemory":
    case "listMemories":
    case "getMemory":
    case "searchMemories":
    case "deleteMemory":
      return <IconBrain size={activityRowIconSize} />;
    case "getGoal":
    case "createGoal":
    case "updateGoal":
      return <IconTargetArrow size={activityRowIconSize} />;
    case "updateTodo":
      return <IconSquareCheck size={activityRowIconSize} />;
    case "loadSkill":
      return <IconBook size={activityRowIconSize} />;
    case "spawnAgent":
    case "sendMessage":
    case "followupTask":
    case "waitAgent":
    case "interruptAgent":
    case "listAgents":
      return <IconRobot size={activityRowIconSize} />;
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
    case "grep":
      return t("action.grep");
    case "glob":
      return t("action.glob");
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
    case "readImage":
      return t("action.readImage");
    case "importFile":
      return t("action.importFile");
    case "saveMemory":
      return t("action.saveMemory");
    case "listMemories":
      return t("action.listMemories");
    case "getMemory":
      return t("action.getMemory");
    case "searchMemories":
      return t("action.searchMemories");
    case "deleteMemory":
      return t("action.deleteMemory");
    case "getGoal":
      return t("action.getGoal");
    case "createGoal":
      return t("action.createGoal");
    case "updateGoal":
      return t("action.updateGoal");
    case "updateTodo":
      return t("action.updateTodo");
    case "loadSkill":
      return t("action.loadSkill");
    case "spawnAgent":
      return t("action.spawnAgent");
    case "sendMessage":
      return t("action.sendMessage");
    case "followupTask":
      return t("action.followupTask");
    case "waitAgent":
      return t("action.waitAgent");
    case "interruptAgent":
      return t("action.interruptAgent");
    case "listAgents":
      return t("action.listAgents");
    case "toolSearch":
      return t("action.toolSearch");
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
    case "grep":
    case "glob":
    case "write":
    case "edit":
    case "delete":
    case "present":
    case "readImage":
    case "importFile":
    case "saveMemory":
    case "listMemories":
    case "getMemory":
    case "searchMemories":
    case "deleteMemory":
    case "getGoal":
    case "createGoal":
    case "updateGoal":
    case "updateTodo":
    case "loadSkill":
    case "spawnAgent":
    case "sendMessage":
    case "followupTask":
    case "waitAgent":
    case "interruptAgent":
    case "listAgents":
    case "toolSearch":
      return presentation.qualifier;
  }
}

function detailLabel(
  label: KnownToolDetailLabel,
  t: ToolCallTranslations,
): string {
  switch (label) {
    case "source":
      return t("field.source");
    case "destination":
      return t("field.destination");
    case "overwrite":
      return t("field.overwrite");
    case "temporary":
      return t("field.temporary");
    case "scope":
      return t("field.scope");
    case "type":
      return t("field.type");
    case "description":
      return t("field.description");
    case "query":
      return t("field.query");
    case "result":
      return t("field.result");
    case "objective":
      return t("field.objective");
    case "status":
      return t("field.status");
    case "createdAt":
      return t("field.createdAt");
    case "updatedAt":
      return t("field.updatedAt");
    case "operation":
      return t("field.operation");
    case "items":
      return t("field.items");
    case "skill":
      return t("field.skill");
    case "task":
      return t("field.task");
    case "message":
      return t("field.message");
    case "agentPath":
      return t("field.agentPath");
    case "forkTurns":
      return t("field.forkTurns");
    case "modelTarget":
      return t("field.modelTarget");
    case "reasoningEffort":
      return t("field.reasoningEffort");
    case "timeout":
      return t("field.timeout");
    case "previousStatus":
      return t("field.previousStatus");
    case "requestedLimit":
      return t("field.requestedLimit");
    case "activationLimit":
      return t("field.activationLimit");
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
      miw="100%"
      w="max-content"
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
        style={{ whiteSpace: "pre" }}
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
        <Text
          px="xs"
          py={rem(2)}
          size="xs"
          c="dimmed"
          ff="monospace"
          miw="100%"
          w="max-content"
          style={{ whiteSpace: "pre" }}
        >
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
      <Stack gap={rem(2)} px="xs" py={rem(6)} bg="default">
        <Text size="xs" c={patchFileActionColor(file)} fw={600}>
          {t(`changeAction.${file.type}`)}
        </Text>
        <Text
          size="xs"
          ff="monospace"
          style={{ overflowWrap: "anywhere", whiteSpace: "normal" }}
        >
          {file.path}
        </Text>
        {destination !== null ? (
          <Text
            size="xs"
            c="dimmed"
            ff="monospace"
            style={{ overflowWrap: "anywhere", whiteSpace: "normal" }}
          >
            → {destination}
          </Text>
        ) : null}
      </Stack>
      {file.type !== "delete" ? (
        <ScrollArea
          scrollbars="x"
          scrollbarSize={activityDetailScrollbarSize}
          {...activityDetailScrollAreaProps}
        >
          <Box miw="max-content">
            {file.type === "add" ? (
              <Stack gap={0}>
                {file.lines.map((content, index) => (
                  <PatchLine
                    key={`add:${index}`}
                    line={{ type: "add", content }}
                  />
                ))}
              </Stack>
            ) : null}
            {file.type === "update" ? (
              <Stack gap="xs" py="xs">
                {file.hunks.map((hunk, index) => (
                  <PatchHunk
                    key={`${hunk.context ?? "root"}:${index}`}
                    hunk={hunk}
                  />
                ))}
              </Stack>
            ) : null}
          </Box>
        </ScrollArea>
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
        <ChatCodeBlock
          code={presentation.detail.output}
          language={presentation.detail.language}
          maxHeight={rem(240)}
        />
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
              {...activityDetailScrollAreaProps}
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
    case "semantic":
      return (
        <Stack gap="sm">
          {presentation.detail.fields.length > 0 ? (
            <Stack gap="sm">
              {presentation.detail.fields.map((field) => (
                <Box key={`${field.label}:${field.value}`}>
                  <Text size="xs" c="dimmed" mb={rem(4)}>
                    {detailLabel(field.label, t)}
                  </Text>
                  <Text
                    size="xs"
                    style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}
                  >
                    {field.value}
                  </Text>
                </Box>
              ))}
            </Stack>
          ) : null}
          {presentation.detail.sections.map((section) => (
            <Box key={`${section.label}:${section.content}`}>
              <Text size="xs" c="dimmed" mb={rem(4)}>
                {detailLabel(section.label, t)}
              </Text>
              <Text
                size="xs"
                style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}
              >
                {section.content}
              </Text>
            </Box>
          ))}
          {presentation.detail.items.length > 0 ? (
            <Stack gap="xs">
              {presentation.detail.items.map((item, index) => (
                <Box
                  key={`${item.title}:${index}`}
                  p="xs"
                  style={{
                    border: activityRowBorder,
                    borderRadius: "var(--mantine-radius-sm)",
                  }}
                >
                  <Text size="xs" fw={500}>
                    {item.title}
                  </Text>
                  {item.subtitle !== null ? (
                    <Text size="xs" c="dimmed">
                      {item.subtitle}
                    </Text>
                  ) : null}
                  {item.content !== null ? (
                    <Text
                      size="xs"
                      mt={rem(4)}
                      style={{
                        overflowWrap: "anywhere",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {item.content}
                    </Text>
                  ) : null}
                </Box>
              ))}
            </Stack>
          ) : null}
        </Stack>
      );
    case "skill":
      return <SkillContentPanel content={presentation.detail.content} />;
  }
}

function RawPayloadContent({
  argumentsText,
  formatJsonValues = true,
  outputText,
  toolName,
}: {
  argumentsText: string;
  formatJsonValues?: boolean;
  outputText: string;
  toolName?: string;
}): ReactElement {
  const t = useTranslations("chat.toolCall");
  const rawText = (value: string): string =>
    formatJsonValues ? formatJson(value) : value;
  return (
    <Stack gap="sm">
      {typeof toolName === "string" ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("toolName")}
          </Text>
          <Code block>{toolName}</Code>
        </Box>
      ) : null}
      {argumentsText.length > 0 ? (
        <Box>
          <Text size="xs" c="dimmed" mb="xs">
            {t("arguments")}
          </Text>
          <ScrollArea.Autosize
            mah={rem(240)}
            scrollbarSize={activityDetailScrollbarSize}
            {...activityDetailScrollAreaProps}
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
            {...activityDetailScrollAreaProps}
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
  const [rawOpened, setRawOpened] = useState(false);
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
  const ariaLabel = [toolCall.name, status].join(" · ");

  return (
    <>
      <ActivityRow
        action={
          <ActionIcon
            size={rem(16)}
            variant="subtle"
            color="gray"
            aria-label={t("viewRawDataFor", { action: toolCall.name })}
            onClick={() => setRawOpened(true)}
          >
            <IconDots size={activityRowIconSize} />
          </ActionIcon>
        }
        ariaLabel={ariaLabel}
        detail={detail}
        icon={<IconTool size={activityRowIconSize} />}
        primary={toolCall.name}
        status={<ToolCallStatusIcon label={status} status={toolCall.status} />}
      />
      {visibleAttachments.length > 0 ? (
        <FileAttachmentList files={visibleAttachments} />
      ) : null}
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
          toolName={toolCall.name}
        />
      </Modal>
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
  const [rawOpened, setRawOpened] = useState(false);
  const detail = presentationDetail(presentation, t);
  const qualifier = presentationQualifier(presentation, t);
  const visibleAttachments = genericVisibleAttachments(
    toolCall,
    hiddenAttachmentUris,
  );
  const action = actionLabel(presentation.action, t);
  const status = t(toolCall.status);
  const ariaLabel = [
    action,
    presentation.subject ?? "",
    qualifier ?? "",
    status,
  ]
    .filter((value) => value.length > 0)
    .join(" · ");

  return (
    <>
      <ActivityRow
        action={
          <ActionIcon
            size={rem(16)}
            variant="subtle"
            color="gray"
            aria-label={t("viewRawDataFor", { action })}
            onClick={() => setRawOpened(true)}
          >
            <IconDots size={activityRowIconSize} />
          </ActionIcon>
        }
        ariaLabel={ariaLabel}
        detail={detail}
        icon={presentationIcon(presentation)}
        primary={action}
        qualifier={qualifier}
        status={<ToolCallStatusIcon label={status} status={toolCall.status} />}
        subject={presentation.subject}
      />
      {visibleAttachments.length > 0 ? (
        <FileAttachmentList files={visibleAttachments} />
      ) : null}
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
          toolName={toolCall.name}
        />
      </Modal>
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
