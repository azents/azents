/* eslint-disable @next/next/no-img-element -- Exchange file image dynamic proxy URLso with next/image optimization not possible */
"use client";

/**
 * file attachment list component.
 *
 * message to attachment Exchange files integration display.
 * - image + preview thumbnail URI: inline preview (download original on click)
 * - image - preview thumbnail URI: download link
 * - text + textPreview: collapsible code block preview
 * - other: filetext + size + download link
 */

import {
  Anchor,
  Box,
  Button,
  Code,
  Collapse,
  Group,
  Modal,
  Text,
} from "@mantine/core";
import {
  IconChevronDown,
  IconChevronRight,
  IconDownload,
  IconFile,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";
import type { FileAttachment } from "../types";

interface FileAttachmentListProps {
  files: FileAttachment[];
}

type FileAvailability = NonNullable<FileAttachment["availability"]>;

/** mediaType imagewhether determine */
function isImageFile(mediaType: string): boolean {
  return mediaType.startsWith("image/");
}

function fileAvailability(file: FileAttachment): FileAvailability {
  return file.availability ?? "available";
}

function isFileAvailable(file: FileAttachment): boolean {
  return fileAvailability(file) === "available";
}

function availabilityLabel(
  t: ReturnType<typeof useTranslations<"chat.attachment">>,
  file: FileAttachment,
): string | null {
  switch (fileAvailability(file)) {
    case "available":
      return null;
    case "expired":
      return t("expired");
    case "unavailable":
      return t("unavailable");
  }
}

/** URI in filetext extract */
export function extractFilename(uri: string): string {
  const parts = uri.split("/");
  return parts[parts.length - 1] ?? uri;
}

/** bartext size human-readable format with convert */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Exchange file text withtext proxy URL create */
export function buildDownloadUrl(file: FileAttachment): string | null {
  if (!file.uri.startsWith("exchange://") || !file.attachmentId) {
    return null;
  }
  return `/api/chat/exchange-files/${encodeURIComponent(file.attachmentId)}/download`;
}

/** text preview exists file of collapsible code block */
function TextPreviewBlock({
  file,
  downloadUrl,
}: {
  file: FileAttachment;
  downloadUrl: string | null;
}): React.ReactElement {
  const t = useTranslations("chat.attachment");
  const [opened, setOpened] = useState(false);
  const toggle = useCallback(() => setOpened((v) => !v), []);
  const displayName = file.name ?? extractFilename(file.uri);
  const statusLabel = availabilityLabel(t, file);

  return (
    <Box mt="xs">
      <Group
        gap={4}
        wrap="nowrap"
        style={{ cursor: "pointer" }}
        onClick={toggle}
      >
        {opened ? (
          <IconChevronDown size={14} />
        ) : (
          <IconChevronRight size={14} />
        )}
        <IconFile size={14} />
        <Text size="sm" fw={500} truncate>
          {displayName}
        </Text>
        {file.size != null && (
          <Text size="xs" c="dimmed">
            ({formatFileSize(file.size)})
          </Text>
        )}
        {statusLabel != null && (
          <Text size="xs" c="red" fw={500}>
            {statusLabel}
          </Text>
        )}
        {downloadUrl != null && (
          <Anchor
            href={downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            size="xs"
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
          >
            <IconDownload size={12} />
          </Anchor>
        )}
      </Group>
      <Collapse expanded={opened}>
        <Code
          block
          mt={4}
          style={{ fontSize: 12, maxHeight: 200, overflow: "auto" }}
        >
          {file.textPreview}
        </Code>
      </Collapse>
    </Box>
  );
}

export function FileAttachmentList({
  files,
}: FileAttachmentListProps): React.ReactElement | null {
  const t = useTranslations("chat.attachment");
  const [previewImage, setPreviewImage] = useState<{
    url: string;
    name: string;
  } | null>(null);

  if (files.length === 0) {
    return null;
  }

  // image (preview thumbnail existstext): inline preview
  const imagesWithThumbnail = files.filter(
    (f) =>
      isFileAvailable(f) &&
      isImageFile(f.mediaType) &&
      f.previewThumbnailUri &&
      f.attachmentId,
  );
  // image (preview thumbnail absenttext): download link
  const imagesWithoutThumbnail = files.filter(
    (f) =>
      isImageFile(f.mediaType) &&
      (!f.previewThumbnailUri || !isFileAvailable(f)),
  );
  // text preview file
  const textPreviewFiles = files.filter(
    (f) => !isImageFile(f.mediaType) && f.textPreview,
  );
  // other file
  const otherFiles = files.filter(
    (f) => !isImageFile(f.mediaType) && !f.textPreview,
  );

  return (
    <>
      {/* thumbnail image preview */}
      {imagesWithThumbnail.length > 0 && (
        <Group gap="xs" mt="xs" wrap="wrap">
          {imagesWithThumbnail.map((file) => {
            const downloadUrl = buildDownloadUrl(file);
            const thumbnailUrl = downloadUrl;
            return (
              <Box
                key={file.uri}
                style={{
                  maxWidth: 200,
                  maxHeight: 200,
                  borderRadius: "var(--mantine-radius-md)",
                  overflow: "hidden",
                  cursor: downloadUrl != null ? "pointer" : "default",
                }}
                onClick={() => {
                  if (downloadUrl == null) {
                    return;
                  }
                  setPreviewImage({
                    url: downloadUrl,
                    name: file.name ?? extractFilename(file.uri),
                  });
                }}
              >
                <img
                  src={thumbnailUrl ?? ""}
                  alt={file.name ?? extractFilename(file.uri)}
                  style={{
                    maxWidth: 200,
                    maxHeight: 200,
                    borderRadius: "var(--mantine-radius-md)",
                    objectFit: "cover",
                  }}
                />
              </Box>
            );
          })}
        </Group>
      )}

      {/* thumbnail absent image: download link */}
      {imagesWithoutThumbnail.length > 0 && (
        <Group gap="xs" mt="xs" wrap="wrap">
          {imagesWithoutThumbnail.map((file) => {
            const displayName = file.name ?? extractFilename(file.uri);
            const statusLabel = availabilityLabel(t, file);
            const downloadUrl = isFileAvailable(file)
              ? buildDownloadUrl(file)
              : null;
            const content = (
              <Group gap={4} wrap="nowrap">
                {downloadUrl != null ? (
                  <IconDownload size={14} />
                ) : (
                  <IconFile size={14} />
                )}
                <Text size="sm" truncate>
                  {displayName}
                </Text>
                {statusLabel != null && (
                  <Text size="xs" c="red" fw={500}>
                    {statusLabel}
                  </Text>
                )}
              </Group>
            );
            if (downloadUrl == null) {
              return <Box key={file.uri}>{content}</Box>;
            }
            return (
              <Anchor
                key={file.uri}
                href={downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                size="sm"
                underline="hover"
              >
                {content}
              </Anchor>
            );
          })}
        </Group>
      )}

      {/* text preview */}
      {textPreviewFiles.map((file) => (
        <TextPreviewBlock
          key={file.uri}
          file={file}
          downloadUrl={isFileAvailable(file) ? buildDownloadUrl(file) : null}
        />
      ))}

      {/* other file: filetext + size + download link */}
      {otherFiles.length > 0 && (
        <Group gap="xs" mt="xs" wrap="wrap">
          {otherFiles.map((file) => {
            const displayName = file.name ?? extractFilename(file.uri);
            const statusLabel = availabilityLabel(t, file);
            const downloadUrl = isFileAvailable(file)
              ? buildDownloadUrl(file)
              : null;
            const content = (
              <Group gap={4} wrap="nowrap">
                <IconFile size={14} />
                <Text size="sm" truncate>
                  {displayName}
                </Text>
                {file.size != null && (
                  <Text size="xs" c="dimmed">
                    ({formatFileSize(file.size)})
                  </Text>
                )}
                {statusLabel != null && (
                  <Text size="xs" c="red" fw={500}>
                    {statusLabel}
                  </Text>
                )}
              </Group>
            );
            if (downloadUrl == null) {
              return <Box key={file.uri}>{content}</Box>;
            }
            return (
              <Anchor
                key={file.uri}
                href={downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                size="sm"
                underline="hover"
              >
                {content}
              </Anchor>
            );
          })}
        </Group>
      )}

      {/* image preview modal */}
      <Modal
        opened={previewImage !== null}
        onClose={() => setPreviewImage(null)}
        size="xl"
        centered
        withCloseButton
        title={previewImage?.name}
      >
        {previewImage && (
          <Box>
            <img
              src={previewImage.url}
              alt={previewImage.name}
              style={{
                width: "100%",
                borderRadius: "var(--mantine-radius-md)",
              }}
            />
            <Group justify="center" mt="md">
              <Button
                component="a"
                href={previewImage.url}
                download={previewImage.name}
                leftSection={<IconDownload size={16} />}
              >
                {t("download")}
              </Button>
            </Group>
          </Box>
        )}
      </Modal>
    </>
  );
}
