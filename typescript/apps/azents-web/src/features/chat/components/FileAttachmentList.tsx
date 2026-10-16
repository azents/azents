/* eslint-disable @next/next/no-img-element -- Exchange file previews use dynamic proxy URLs */
"use client";

import { ActionIcon, Box, Group, Paper, rem, Text } from "@mantine/core";
import { IconDownload, IconFile } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import {
  useAttachmentStrip,
  useFileAttachmentList,
} from "../containers/useFileAttachmentList";
import {
  availabilityLabel,
  buildDownloadUrl,
  extractFilename,
  fileTypeLabel,
  formatFileSize,
  isFileAvailable,
  isImageFile,
  previewSelection,
} from "../fileAttachmentPresentation";
import { AttachmentPreviewViewer } from "./AttachmentPreviewViewer";
import type { FileAttachment } from "@azents/session-core/types";
import type { KeyboardEvent } from "react";

export {
  buildDownloadUrl,
  extractFilename,
  formatFileSize,
} from "../fileAttachmentPresentation";

function activateDownload(downloadUrl: string | null): void {
  if (downloadUrl === null) {
    return;
  }
  window.open(downloadUrl, "_blank", "noopener,noreferrer");
}

function AttachmentTile({
  file,
  onPreview,
}: {
  file: FileAttachment;
  onPreview: (file: FileAttachment) => void;
}): React.ReactElement {
  const t = useTranslations("chat.attachment");
  const displayName = file.name ?? extractFilename(file.uri);
  const downloadUrl = isFileAvailable(file) ? buildDownloadUrl(file) : null;
  const selection = previewSelection(file);
  const statusLabel = availabilityLabel(t, file);
  const thumbnailUrl =
    isFileAvailable(file) && isImageFile(file.mediaType) ? downloadUrl : null;
  const canActivate = selection !== null || downloadUrl !== null;

  const activate = (): void => {
    if (selection !== null) {
      onPreview(file);
      return;
    }
    activateDownload(downloadUrl);
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (!canActivate || (event.key !== "Enter" && event.key !== " ")) {
      return;
    }
    event.preventDefault();
    activate();
  };

  return (
    <Paper
      p="xs"
      radius="sm"
      shadow="xs"
      {...(canActivate
        ? {
            role: "button",
            tabIndex: 0,
            onClick: (event: React.MouseEvent<HTMLDivElement>) => {
              event.currentTarget.focus();
              activate();
            },
          }
        : {})}
      aria-label={
        selection !== null
          ? t("openPreview", { name: displayName })
          : downloadUrl !== null
            ? t("downloadFile", { name: displayName })
            : `${displayName} ${statusLabel ?? ""}`.trim()
      }
      onKeyDown={handleKeyDown}
      style={{
        alignItems: "center",
        cursor: canActivate ? "pointer" : "default",
        display: "flex",
        flex: "0 0 auto",
        gap: "var(--mantine-spacing-xs)",
        width: rem(200),
      }}
    >
      {thumbnailUrl ? (
        <img
          src={thumbnailUrl}
          alt=""
          style={{
            borderRadius: "var(--mantine-radius-sm)",
            height: rem(40),
            objectFit: "cover",
            width: rem(40),
          }}
        />
      ) : (
        <Box
          bg="var(--mantine-color-default)"
          style={{
            alignItems: "center",
            borderRadius: "var(--mantine-radius-sm)",
            display: "flex",
            flex: `0 0 ${rem(40)}`,
            height: rem(40),
            justifyContent: "center",
          }}
        >
          <IconFile size={20} color="var(--mantine-color-dimmed)" />
        </Box>
      )}

      <Box style={{ flex: 1, minWidth: 0 }}>
        <Text size="xs" fw={500} truncate>
          {displayName}
        </Text>
        <Text size="xs" c={statusLabel ? "red" : "dimmed"} truncate>
          {statusLabel ??
            [
              fileTypeLabel(file),
              file.size == null ? null : formatFileSize(file.size),
            ]
              .filter(Boolean)
              .join(" · ")}
        </Text>
      </Box>

      {downloadUrl ? (
        <ActionIcon
          component="a"
          href={downloadUrl}
          target="_blank"
          rel="noopener noreferrer"
          download={displayName}
          variant="subtle"
          color="gray"
          size="sm"
          aria-label={t("downloadFile", { name: displayName })}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <IconDownload size={16} />
        </ActionIcon>
      ) : null}
    </Paper>
  );
}

export function AttachmentStripView({
  files,
  onPreview,
  ref,
  style,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onClickCapture,
}: ReturnType<typeof useAttachmentStrip>): React.ReactElement {
  return (
    <Group
      ref={ref}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClickCapture={onClickCapture}
      gap="xs"
      py="xs"
      wrap="nowrap"
      w="100%"
      style={{
        ...style,
        overflowX: "auto",
        overscrollBehaviorInline: "contain",
        scrollbarWidth: "none",
      }}
    >
      {files.map((file) => (
        <AttachmentTile key={file.uri} file={file} onPreview={onPreview} />
      ))}
    </Group>
  );
}

function AgentImageGallery({
  files,
  onPreview,
}: {
  files: FileAttachment[];
  onPreview: (file: FileAttachment) => void;
}): React.ReactElement {
  const visibleFiles = files.slice(0, 4);
  const hiddenCount = Math.max(0, files.length - visibleFiles.length);
  const isSingleImage = files.length === 1;

  return (
    <Box
      style={{
        display: "grid",
        gap: "var(--mantine-spacing-xs)",
        gridTemplateColumns: isSingleImage
          ? "minmax(0, 1fr)"
          : "repeat(2, minmax(0, 1fr))",
        maxWidth: rem(480),
      }}
    >
      {visibleFiles.map((file, index) => {
        const displayName = file.name ?? extractFilename(file.uri);
        const isCountCell =
          hiddenCount > 0 && index === visibleFiles.length - 1;
        const activationFile = isCountCell ? (files.at(4) ?? file) : file;
        const selection = previewSelection(activationFile);
        const downloadUrl = buildDownloadUrl(activationFile);
        const activationDisplayName =
          activationFile.name ?? extractFilename(activationFile.uri);
        const activate = (): void => {
          if (selection !== null) {
            onPreview(activationFile);
            return;
          }
          activateDownload(downloadUrl);
        };
        return (
          <Box
            key={file.uri}
            role="button"
            tabIndex={0}
            aria-label={activationDisplayName}
            style={{
              ...(!isSingleImage
                ? { aspectRatio: "1 / 1" }
                : { maxHeight: rem(480) }),
              borderRadius: "var(--mantine-radius-md)",
              cursor: "pointer",
              overflow: "hidden",
              position: "relative",
            }}
            onClick={(event) => {
              event.currentTarget.focus();
              activate();
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                activate();
              }
            }}
          >
            <img
              src={downloadUrl ?? ""}
              alt={displayName}
              style={{
                borderRadius: "var(--mantine-radius-md)",
                height: isSingleImage ? "auto" : "100%",
                maxHeight: rem(480),
                objectFit: isSingleImage ? "contain" : "cover",
                width: "100%",
              }}
            />
            {isCountCell ? (
              <Box
                style={{
                  alignItems: "center",
                  background:
                    "color-mix(in srgb, var(--mantine-color-black) 56%, transparent)",
                  display: "flex",
                  inset: 0,
                  justifyContent: "center",
                  position: "absolute",
                }}
              >
                <Text c="white" fw={700} size="xl">
                  +{hiddenCount}
                </Text>
              </Box>
            ) : null}
          </Box>
        );
      })}
    </Box>
  );
}

const AttachmentStrip = createReactContainer(
  "AttachmentStrip",
  useAttachmentStrip,
  AttachmentStripView,
);
export function FileAttachmentListView({
  files,
  presentation = "agent",
  prominentImages,
  compactFiles,
  previewSelections,
  selectedIndex,
  openPreview,
  closePreview,
  movePreview,
}: ReturnType<typeof useFileAttachmentList>): React.ReactElement | null {
  if (files.length === 0) {
    return null;
  }

  const showAgentGallery =
    presentation === "agent" && prominentImages.length > 0;
  const showMixedGroup = showAgentGallery && compactFiles.length > 0;
  const selection =
    selectedIndex === null ? null : (previewSelections[selectedIndex] ?? null);

  const content =
    presentation === "compact" || !showAgentGallery ? (
      <AttachmentStrip files={files} onPreview={openPreview} />
    ) : showMixedGroup ? (
      <Paper withBorder radius="md" p="xs" mt="xs">
        <AgentImageGallery files={prominentImages} onPreview={openPreview} />
        <AttachmentStrip files={compactFiles} onPreview={openPreview} />
      </Paper>
    ) : (
      <Box mt="xs">
        <AgentImageGallery files={prominentImages} onPreview={openPreview} />
      </Box>
    );

  return (
    <>
      {content}
      {selection && selectedIndex !== null ? (
        <AttachmentPreviewViewer
          opened
          onClose={closePreview}
          {...(selectedIndex > 0 ? { onPrevious: () => movePreview(-1) } : {})}
          {...(selectedIndex < previewSelections.length - 1
            ? { onNext: () => movePreview(1) }
            : {})}
          position={{
            current: selectedIndex + 1,
            total: previewSelections.length,
          }}
          name={selection.file.name ?? extractFilename(selection.file.uri)}
          mediaType={selection.file.mediaType}
          size={selection.file.size}
          downloadUrl={selection.downloadUrl}
          preview={selection.preview}
        />
      ) : null}
    </>
  );
}

export const FileAttachmentList = createReactContainer(
  "FileAttachmentList",
  useFileAttachmentList,
  FileAttachmentListView,
);
