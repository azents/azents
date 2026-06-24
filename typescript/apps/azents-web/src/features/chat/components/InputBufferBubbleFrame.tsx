"use client";

/** common layout for input-buffer bubbles. */

import { Box, Group, Paper, rem } from "@mantine/core";
import { extractFilename, FileAttachmentList } from "./FileAttachmentList";
import { MarkdownContent } from "./MarkdownContent";
import type { FileAttachment } from "../types";

interface InputBufferBubbleFrameProps {
  content: string;
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

export function InputBufferBubbleFrame({
  content,
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
          <MarkdownContent>{content}</MarkdownContent>
        </Paper>
        {actions}
      </Box>
    </Group>
  );
}
