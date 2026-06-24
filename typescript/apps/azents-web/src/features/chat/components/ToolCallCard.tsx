"use client";

/**
 * Tool call wheneachtext card.
 *
 * tool call name, arguments, result display.
 * running tool loading display, complete tool result display.
 */

import {
  Accordion,
  Badge,
  Code,
  Group,
  Loader,
  Paper,
  rem,
  ScrollArea,
  Text,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconChevronRight,
  IconCircleOff,
  IconPlayerStop,
  IconTool,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { FileAttachmentList } from "./FileAttachmentList";
import type { ActiveToolCall } from "../types";

/** Format JSON string. Return original when parsing fails. */
function formatJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

interface ToolCallCardProps {
  toolCall: ActiveToolCall;
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

function toolCallStatusIcon(
  status: ActiveToolCall["status"],
): React.ReactElement {
  switch (status) {
    case "running":
      return <Loader size={16} />;
    case "failed":
      return <IconAlertTriangle size={16} />;
    case "cancelled":
      return <IconCircleOff size={16} />;
    case "interrupted":
      return <IconPlayerStop size={16} />;
    case "preparing":
    case "completed":
      return <IconTool size={16} />;
  }
}

export function ToolCallCard({
  toolCall,
}: ToolCallCardProps): React.ReactElement {
  const t = useTranslations("chat.toolCall");
  const [openedToolCallId, setOpenedToolCallId] = useState<string | null>(null);
  const isPreparing = toolCall.status === "preparing";
  const isOpened = openedToolCallId === toolCall.id;

  if (isPreparing) {
    return (
      <Paper withBorder radius="md" p="sm" my="xs">
        <Group gap="xs" wrap="nowrap">
          <Loader size="sm" />
          <Text size="sm" fw={500} c="dimmed">
            {t("preparing")}
          </Text>
        </Group>
      </Paper>
    );
  }

  const formattedArgs = toolCall.arguments
    ? formatJson(toolCall.arguments)
    : "";
  const formattedResult = toolCall.result ? formatJson(toolCall.result) : null;

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
            <Text size="xs" c="dimmed" mb={4}>
              {t("arguments")}
            </Text>
            <ScrollArea.Autosize mah={200}>
              <Code block style={{ fontSize: 12 }}>
                {formattedArgs}
              </Code>
            </ScrollArea.Autosize>
            {formattedResult && (
              <>
                <Text size="xs" c="dimmed" mt="sm" mb={4}>
                  {t("result")}
                </Text>
                <ScrollArea.Autosize mah={200}>
                  <Code block style={{ fontSize: 12 }}>
                    {formattedResult}
                  </Code>
                </ScrollArea.Autosize>
              </>
            )}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
      {/* attachment file accordion outside to display — always expanded status with user totext exposed */}
      {toolCall.attachments && toolCall.attachments.length > 0 && (
        <FileAttachmentList files={toolCall.attachments} />
      )}
    </>
  );
}
