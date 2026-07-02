"use client";

/** common layout for input-buffer bubbles. */

import { Box, Group, Paper, rem, Stack, Text } from "@mantine/core";
import { extractFilename, FileAttachmentList } from "./FileAttachmentList";
import { MarkdownContent } from "./MarkdownContent";
import type { ChatAction, FileAttachment } from "../types";

interface InputBufferBubbleFrameProps {
  content: string;
  action?: ChatAction | null;
  attachments: string[];
  attachmentFiles?: FileAttachment[];
  opacity: number;
  actions: React.ReactNode;
}

function toPendingAttachment(uri: string): FileAttachment {
  return {
    uri,
    mediaType: "application/octet-stream",
    name: extractFilename(uri),
  };
}

function actionLabel(action: ChatAction): string {
  switch (action.type) {
    case "command":
      return `/${action.name}`;
    case "goal":
      return "/goal";
    case "skill":
      return "/skill";
  }
}

function ActionPill({ action }: { action: ChatAction }): React.ReactElement {
  return (
    <Group
      gap={rem(4)}
      wrap="nowrap"
      px={rem(7)}
      py={rem(2)}
      style={{
        alignSelf: "flex-start",
        background: "var(--mantine-color-blue-light)",
        borderRadius: rem(999),
        maxWidth: "100%",
      }}
    >
      <Text size="xs" fw={700} c="blue" truncate>
        {actionLabel(action)}
      </Text>
    </Group>
  );
}

export function InputBufferBubbleFrame({
  content,
  action,
  attachments,
  attachmentFiles,
  opacity,
  actions,
}: InputBufferBubbleFrameProps): React.ReactElement {
  const files = attachmentFiles ?? attachments.map(toPendingAttachment);

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
        {files.length > 0 && <FileAttachmentList files={files} />}
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
            opacity,
          }}
        >
          <Stack gap={rem(8)} align="flex-start">
            {action && <ActionPill action={action} />}
            <MarkdownContent>{content}</MarkdownContent>
          </Stack>
        </Paper>
        {actions}
      </Box>
    </Group>
  );
}
