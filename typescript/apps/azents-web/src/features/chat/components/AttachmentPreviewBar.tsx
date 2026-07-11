"use client";

/**
 * attachment file preview bar.
 *
 * input area above to pending attachment files display.
 * each file: image thumbnail preview, filetext, status badge, remove button.
 */

import {
  ActionIcon,
  Badge,
  Box,
  Group,
  Loader,
  Paper,
  rem,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconFile, IconPhoto, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PendingFile, UploadErrorReason } from "../hooks/useFileUpload";

/** file icon/thumbnail container common style */
const iconBoxStyle: React.CSSProperties = {
  width: rem(40),
  height: rem(40),
  borderRadius: "var(--mantine-radius-sm)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

interface AttachmentPreviewBarProps {
  pendingFiles: PendingFile[];
  onRemove: (id: string) => void;
}

/** file imagewhether determine */
function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

/** status to text badge colorabove */
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
  t: ReturnType<typeof useTranslations>,
): string {
  switch (reason) {
    case "fileTooLarge":
      return t("errorReason.fileTooLarge");
    case "invalidRequest":
      return t("errorReason.invalidRequest");
    case "unauthorized":
      return t("errorReason.unauthorized");
    case "forbidden":
      return t("errorReason.forbidden");
    case "unsupportedType":
      return t("errorReason.unsupportedType");
    case "serverError":
      return t("errorReason.serverError");
    case "networkError":
      return t("errorReason.networkError");
    case "invalidResponse":
      return t("errorReason.invalidResponse");
    case "unknown":
    case null:
      return t("errorReason.unknown");
  }
}

/** image file thumbnail preview */
function ImagePreview({ file }: { file: File }): React.ReactElement {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setSrc(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [file]);

  if (!src) {
    return (
      <Box style={iconBoxStyle} bg="var(--mantine-color-default)">
        <IconPhoto size={20} color="var(--mantine-color-dimmed)" />
      </Box>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- blob URL previewso with next/image not possible
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
  pendingFiles,
  onRemove,
}: AttachmentPreviewBarProps): React.ReactElement | null {
  const t = useTranslations("chat.attachment");
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [overflowEdges, setOverflowEdges] = useState({
    left: false,
    right: false,
  });
  const updateOverflowEdges = useCallback((): void => {
    const element = scrollerRef.current;
    if (element === null) {
      return;
    }
    const maxScrollLeft = Math.max(
      0,
      element.scrollWidth - element.clientWidth,
    );
    setOverflowEdges({
      left: element.scrollLeft > 1,
      right: element.scrollLeft < maxScrollLeft - 1,
    });
  }, []);

  useEffect(() => {
    const element = scrollerRef.current;
    if (element === null) {
      return;
    }
    updateOverflowEdges();
    const observer = new ResizeObserver(updateOverflowEdges);
    observer.observe(element);
    for (const child of element.children) {
      observer.observe(child);
    }
    element.addEventListener("scroll", updateOverflowEdges, { passive: true });
    return () => {
      observer.disconnect();
      element.removeEventListener("scroll", updateOverflowEdges);
    };
  }, [pendingFiles.length, updateOverflowEdges]);

  const fadeWidth = rem(40);
  let maskImage = "none";
  if (overflowEdges.left && overflowEdges.right) {
    maskImage = `linear-gradient(to right, transparent 0, var(--mantine-color-black) ${fadeWidth}, var(--mantine-color-black) calc(100% - ${fadeWidth}), transparent 100%)`;
  } else if (overflowEdges.left) {
    maskImage = `linear-gradient(to right, transparent 0, var(--mantine-color-black) ${fadeWidth}, var(--mantine-color-black) 100%)`;
  } else if (overflowEdges.right) {
    maskImage = `linear-gradient(to right, var(--mantine-color-black) 0, var(--mantine-color-black) calc(100% - ${fadeWidth}), transparent 100%)`;
  }

  // status translation key mapping
  const statusLabels: Record<PendingFile["status"], string> = useMemo(
    () => ({
      pending: t("attach"),
      uploading: t("uploading"),
      done: t("download"),
      error: t("uploadError"),
    }),
    [t],
  );

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
      {pendingFiles.map((pf) => {
        const errorReason =
          pf.status === "error"
            ? getErrorReasonLabel(pf.errorReason ?? null, t)
            : null;
        const errorTooltip = pf.errorDetail
          ? `${errorReason ?? statusLabels[pf.status]}: ${pf.errorDetail}`
          : errorReason;

        return (
          <Paper
            key={pf.id}
            p="xs"
            radius="sm"
            shadow="xs"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--mantine-spacing-xs)",
              width: rem(200),
              flex: "0 0 auto",
            }}
          >
            {/* thumbnail or file icon */}
            {isImageFile(pf.file) ? (
              <ImagePreview file={pf.file} />
            ) : (
              <Box style={iconBoxStyle} bg="var(--mantine-color-default)">
                <IconFile size={20} color="var(--mantine-color-dimmed)" />
              </Box>
            )}

            {/* filetext + status */}
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Text size="xs" truncate>
                {pf.file.name}
              </Text>
              <Group gap={rem(4)} wrap="nowrap">
                {pf.status === "uploading" && <Loader size={10} />}
                <Badge
                  size="xs"
                  variant="light"
                  color={getStatusColor(pf.status)}
                >
                  {statusLabels[pf.status]}
                </Badge>
                {errorReason ? (
                  <Tooltip label={errorTooltip} withArrow>
                    <Text size="xs" c="red" truncate maw={rem(110)}>
                      {errorReason}
                    </Text>
                  </Tooltip>
                ) : null}
              </Group>
            </Box>

            {/* remove button */}
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              onClick={() => onRemove(pf.id)}
              aria-label={t("removeFile")}
            >
              <IconX size={14} />
            </ActionIcon>
          </Paper>
        );
      })}
    </Group>
  );
});
