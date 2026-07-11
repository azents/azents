/* eslint-disable @next/next/no-img-element -- Exchange file previews use dynamic proxy URLs */
"use client";

import { ActionIcon, Box, Group, Paper, rem, Text } from "@mantine/core";
import { IconDownload, IconFile } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import {
  type CSSProperties,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  type AttachmentPreviewContent,
  AttachmentPreviewViewer,
} from "./AttachmentPreviewViewer";
import type { FileAttachment } from "../types";

interface FileAttachmentListProps {
  files: FileAttachment[];
  presentation?: "agent" | "compact";
}

type FileAvailability = NonNullable<FileAttachment["availability"]>;

interface PreviewSelection {
  file: FileAttachment;
  preview: AttachmentPreviewContent;
  downloadUrl: string;
}

interface OverflowMaskState {
  ref: React.RefObject<HTMLDivElement | null>;
  style: CSSProperties;
}

const fadeWidth = rem(40);

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

export function extractFilename(uri: string): string {
  const parts = uri.split("/");
  return parts[parts.length - 1] ?? uri;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function buildDownloadUrl(file: FileAttachment): string | null {
  if (!file.uri.startsWith("exchange://") || !file.attachmentId) {
    return null;
  }
  return `/api/chat/exchange-files/${encodeURIComponent(file.attachmentId)}/download`;
}

function fileTypeLabel(file: FileAttachment): string {
  const extension = (file.name ?? extractFilename(file.uri))
    .split(".")
    .at(-1)
    ?.toUpperCase();
  return extension && extension.length <= 6
    ? extension
    : file.mediaType.split("/").at(-1)?.toUpperCase() || "FILE";
}

function previewSelection(file: FileAttachment): PreviewSelection | null {
  if (!isFileAvailable(file)) {
    return null;
  }
  const downloadUrl = buildDownloadUrl(file);
  if (downloadUrl === null) {
    return null;
  }
  if (isImageFile(file.mediaType)) {
    return {
      file,
      downloadUrl,
      preview: {
        type: "image",
        url: downloadUrl,
        altText: file.name ?? extractFilename(file.uri),
      },
    };
  }
  if (file.textPreview) {
    return {
      file,
      downloadUrl,
      preview: {
        type: "text",
        text: file.textPreview,
      },
    };
  }
  return {
    file,
    downloadUrl,
    preview: { type: "unsupported" },
  };
}

function useOverflowMask(): OverflowMaskState {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });

  const update = useCallback((): void => {
    const element = ref.current;
    if (element === null) {
      return;
    }
    const maxScrollLeft = Math.max(
      0,
      element.scrollWidth - element.clientWidth,
    );
    setEdges({
      left: element.scrollLeft > 1,
      right: element.scrollLeft < maxScrollLeft - 1,
    });
  }, []);

  useEffect(() => {
    const element = ref.current;
    if (element === null) {
      return;
    }
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    for (const child of element.children) {
      observer.observe(child);
    }
    element.addEventListener("scroll", update, { passive: true });
    return () => {
      observer.disconnect();
      element.removeEventListener("scroll", update);
    };
  }, [update]);

  let maskImage = "none";
  if (edges.left && edges.right) {
    maskImage = `linear-gradient(to right, transparent 0, var(--mantine-color-black) ${fadeWidth}, var(--mantine-color-black) calc(100% - ${fadeWidth}), transparent 100%)`;
  } else if (edges.left) {
    maskImage = `linear-gradient(to right, transparent 0, var(--mantine-color-black) ${fadeWidth}, var(--mantine-color-black) 100%)`;
  } else if (edges.right) {
    maskImage = `linear-gradient(to right, var(--mantine-color-black) 0, var(--mantine-color-black) calc(100% - ${fadeWidth}), transparent 100%)`;
  }

  return {
    ref,
    style: {
      maskImage,
      WebkitMaskImage: maskImage,
    },
  };
}

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
  onPreview: (selection: PreviewSelection) => void;
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
      onPreview(selection);
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

function AttachmentStrip({
  files,
  onPreview,
}: {
  files: FileAttachment[];
  onPreview: (selection: PreviewSelection) => void;
}): React.ReactElement {
  const { ref, style } = useOverflowMask();
  const pointerStartX = useRef<number | null>(null);
  const dragged = useRef(false);

  return (
    <Group
      ref={ref}
      onPointerDown={(event) => {
        pointerStartX.current = event.clientX;
        dragged.current = false;
      }}
      onPointerMove={(event) => {
        if (
          pointerStartX.current !== null &&
          Math.abs(event.clientX - pointerStartX.current) > 6
        ) {
          dragged.current = true;
        }
      }}
      onPointerUp={() => {
        pointerStartX.current = null;
      }}
      onClickCapture={(event) => {
        if (dragged.current) {
          event.preventDefault();
          event.stopPropagation();
          dragged.current = false;
        }
      }}
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
  onPreview: (selection: PreviewSelection) => void;
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
            onPreview(selection);
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

export function FileAttachmentList({
  files,
  presentation = "agent",
}: FileAttachmentListProps): React.ReactElement | null {
  const [selection, setSelection] = useState<PreviewSelection | null>(null);
  const previewOpenerRef = useRef<HTMLElement | null>(null);

  const openPreview = useCallback((nextSelection: PreviewSelection): void => {
    if (document.activeElement instanceof HTMLElement) {
      previewOpenerRef.current = document.activeElement;
    }
    setSelection(nextSelection);
  }, []);
  const closePreview = useCallback((): void => {
    setSelection(null);
    requestAnimationFrame(() => previewOpenerRef.current?.focus());
  }, []);

  if (files.length === 0) {
    return null;
  }

  const prominentImages = files.filter(
    (file) =>
      isImageFile(file.mediaType) &&
      isFileAvailable(file) &&
      buildDownloadUrl(file) !== null,
  );
  const compactFiles = files.filter((file) => !prominentImages.includes(file));
  const showAgentGallery =
    presentation === "agent" && prominentImages.length > 0;
  const showMixedGroup = showAgentGallery && compactFiles.length > 0;

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
      {selection ? (
        <AttachmentPreviewViewer
          opened
          onClose={closePreview}
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
