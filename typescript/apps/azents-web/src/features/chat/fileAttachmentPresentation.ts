import type { AttachmentPreviewContent } from "./components/AttachmentPreviewViewer";
import type { FileAttachment } from "@azents/session-core/types";
import type { useTranslations } from "next-intl";

type FileAvailability = NonNullable<FileAttachment["availability"]>;

interface PreviewSelection {
  file: FileAttachment;
  preview: AttachmentPreviewContent;
  downloadUrl: string;
}

const previewHistoryStateKey = "__azentsAttachmentPreview";

interface PreviewHistoryMarker {
  viewerId: string;
  index: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function previewHistoryMarker(
  state: unknown,
): PreviewHistoryMarker | null {
  if (!isRecord(state)) {
    return null;
  }
  const marker = state[previewHistoryStateKey];
  if (
    !isRecord(marker) ||
    typeof marker.viewerId !== "string" ||
    typeof marker.index !== "number"
  ) {
    return null;
  }
  return { viewerId: marker.viewerId, index: marker.index };
}

export function historyStateWithPreview(
  viewerId: string,
  index: number,
): Record<string, unknown> {
  return {
    [previewHistoryStateKey]: { viewerId, index },
  };
}

export function isImageFile(mediaType: string): boolean {
  return mediaType.startsWith("image/");
}

function isMarkdownFile(file: FileAttachment): boolean {
  const mediaType = file.mediaType.split(";", 1)[0]?.trim().toLowerCase();
  if (mediaType === "text/markdown") {
    return true;
  }
  const name = file.name ?? extractFilename(file.uri);
  const normalizedName = name.toLowerCase();
  return [".md", ".markdown", ".mdx"].some((extension) =>
    normalizedName.endsWith(extension),
  );
}

export function fileAvailability(file: FileAttachment): FileAvailability {
  return file.availability ?? "available";
}

export function isFileAvailable(file: FileAttachment): boolean {
  return fileAvailability(file) === "available";
}

export function availabilityLabel(
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

export function fileTypeLabel(file: FileAttachment): string {
  const extension = (file.name ?? extractFilename(file.uri))
    .split(".")
    .at(-1)
    ?.toUpperCase();
  return extension && extension.length <= 6
    ? extension
    : file.mediaType.split("/").at(-1)?.toUpperCase() || "FILE";
}

export function previewSelection(
  file: FileAttachment,
): PreviewSelection | null {
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
  if (file.textPreview != null) {
    return {
      file,
      downloadUrl,
      preview: {
        type: isMarkdownFile(file) ? "markdown" : "text",
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
