"use client";

/** Pure attachment file preview bar. */

import {
  ActionIcon,
  Badge,
  Box,
  Group,
  Loader,
  Paper,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import { IconFile, IconPhoto, IconX } from "@tabler/icons-react";
import { memo } from "react";
import type {
  PendingFile,
  UploadErrorReason,
} from "@/shared/file-upload/useFileUpload";
import type { RefObject } from "react";

const iconBoxStyle: React.CSSProperties = {
  width: rem(40),
  height: rem(40),
  borderRadius: "var(--mantine-radius-sm)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

export interface AttachmentPreviewBarLabels {
  removeFile: string;
  statuses: Record<PendingFile["status"], string>;
  errors: Record<Exclude<UploadErrorReason, null>, string>;
}

export interface AttachmentPreviewBarProps {
  labels: AttachmentPreviewBarLabels;
  maskImage: string;
  pendingFiles: PendingFile[];
  previewUrls: ReadonlyMap<string, string>;
  scrollerRef: RefObject<HTMLDivElement | null>;
  onRemove: (id: string) => void;
}

function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

function getStatusColor(status: PendingFile["status"]): string {
  switch (status) {
    case "pending":
      return "gray";
    case "uploading":
      return "blue";
    case "done":
      return "green";
    case "error":
      return "red";
  }
}

function getErrorReasonLabel(
  reason: UploadErrorReason | null,
  labels: AttachmentPreviewBarLabels["errors"],
): string {
  switch (reason) {
    case "fileTooLarge":
      return labels.fileTooLarge;
    case "invalidRequest":
      return labels.invalidRequest;
    case "unauthorized":
      return labels.unauthorized;
    case "forbidden":
      return labels.forbidden;
    case "unsupportedType":
      return labels.unsupportedType;
    case "serverError":
      return labels.serverError;
    case "networkError":
      return labels.networkError;
    case "invalidResponse":
      return labels.invalidResponse;
    case "unknown":
    case null:
      return labels.unknown;
  }
}

function ImagePreview({ src }: { src: string | null }): React.ReactElement {
  if (src === null) {
    return (
      <Box style={iconBoxStyle} bg="var(--mantine-color-default)">
        <IconPhoto size={20} color="var(--mantine-color-dimmed)" />
      </Box>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- blob URLs cannot use next/image
    <img
      src={src}
      alt=""
      style={{
        width: rem(40),
        height: rem(40),
        borderRadius: "var(--mantine-radius-sm)",
        objectFit: "cover",
      }}
    />
  );
}

export const AttachmentPreviewBar = memo(function AttachmentPreviewBar({
  labels,
  maskImage,
  pendingFiles,
  previewUrls,
  scrollerRef,
  onRemove,
}: AttachmentPreviewBarProps): React.ReactElement | null {
  if (pendingFiles.length === 0) {
    return null;
  }

  return (
    <Group
      ref={scrollerRef}
      gap="xs"
      px="md"
      py="xs"
      wrap="nowrap"
      style={{
        maskImage,
        overflowX: "auto",
        overscrollBehaviorInline: "contain",
        WebkitMaskImage: maskImage,
      }}
    >
      {pendingFiles.map((pendingFile) => {
        const errorReason =
          pendingFile.status === "error"
            ? getErrorReasonLabel(
                pendingFile.errorReason ?? null,
                labels.errors,
              )
            : null;
        const errorMessage = pendingFile.errorDetail
          ? `${errorReason ?? labels.statuses[pendingFile.status]}: ${pendingFile.errorDetail}`
          : errorReason;

        return (
          <Paper
            key={pendingFile.id}
            p="xs"
            radius="sm"
            shadow="xs"
            style={{
              display: "flex",
              alignItems:
                pendingFile.status === "error" ? "flex-start" : "center",
              gap: "var(--mantine-spacing-xs)",
              width:
                pendingFile.status === "error"
                  ? `min(100%, ${rem(320)})`
                  : rem(200),
              flex: "0 0 auto",
            }}
          >
            {isImageFile(pendingFile.file) ? (
              <ImagePreview src={previewUrls.get(pendingFile.id) ?? null} />
            ) : (
              <Box style={iconBoxStyle} bg="var(--mantine-color-default)">
                <IconFile size={20} color="var(--mantine-color-dimmed)" />
              </Box>
            )}

            <Box style={{ flex: 1, minWidth: 0 }}>
              {pendingFile.status === "error" ? (
                <Stack gap={rem(4)}>
                  <Group gap="xs" justify="space-between" wrap="nowrap">
                    <Text
                      size="xs"
                      style={{ minWidth: 0, overflowWrap: "anywhere" }}
                    >
                      {pendingFile.file.name}
                    </Text>
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      size="sm"
                      onClick={() => onRemove(pendingFile.id)}
                      aria-label={labels.removeFile}
                      style={{ flexShrink: 0 }}
                    >
                      <IconX size={14} />
                    </ActionIcon>
                  </Group>
                  <Box
                    px="xs"
                    py={rem(6)}
                    style={{
                      borderRadius: "var(--mantine-radius-sm)",
                      background: "var(--mantine-color-red-light)",
                    }}
                  >
                    <Text size="xs" fw={700} c="red">
                      {labels.statuses.error}
                    </Text>
                    {errorMessage ? (
                      <Text
                        size="xs"
                        c="red"
                        style={{ overflowWrap: "anywhere" }}
                      >
                        {errorMessage}
                      </Text>
                    ) : null}
                  </Box>
                </Stack>
              ) : (
                <>
                  <Text size="xs" truncate>
                    {pendingFile.file.name}
                  </Text>
                  <Group gap={rem(4)} wrap="nowrap">
                    {pendingFile.status === "uploading" && <Loader size={10} />}
                    <Badge
                      size="xs"
                      variant="light"
                      color={getStatusColor(pendingFile.status)}
                    >
                      {labels.statuses[pendingFile.status]}
                    </Badge>
                  </Group>
                </>
              )}
            </Box>
            {pendingFile.status !== "error" ? (
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                onClick={() => onRemove(pendingFile.id)}
                aria-label={labels.removeFile}
              >
                <IconX size={14} />
              </ActionIcon>
            ) : null}
          </Paper>
        );
      })}
    </Group>
  );
});
