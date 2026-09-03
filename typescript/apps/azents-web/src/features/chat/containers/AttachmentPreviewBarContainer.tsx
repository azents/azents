"use client";

import { rem } from "@mantine/core";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AttachmentPreviewBar } from "../components/AttachmentPreviewBar";
import type { AttachmentPreviewBarLabels } from "../components/AttachmentPreviewBar";
import type { PendingFile } from "../hooks/useFileUpload";

interface AttachmentPreviewBarContainerProps {
  pendingFiles: PendingFile[];
  onRemove: (id: string) => void;
}

function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

export function AttachmentPreviewBarContainer({
  pendingFiles,
  onRemove,
}: AttachmentPreviewBarContainerProps): React.ReactElement | null {
  const t = useTranslations("chat.attachment");
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [overflowEdges, setOverflowEdges] = useState({
    left: false,
    right: false,
  });
  const [previewUrls, setPreviewUrls] = useState<ReadonlyMap<string, string>>(
    () => new Map(),
  );

  useEffect(() => {
    const nextPreviewUrls = new Map<string, string>();
    for (const pendingFile of pendingFiles) {
      if (isImageFile(pendingFile.file)) {
        nextPreviewUrls.set(
          pendingFile.id,
          URL.createObjectURL(pendingFile.file),
        );
      }
    }
    setPreviewUrls(nextPreviewUrls);
    return () => {
      for (const url of nextPreviewUrls.values()) {
        URL.revokeObjectURL(url);
      }
    };
  }, [pendingFiles]);

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

  const labels = useMemo<AttachmentPreviewBarLabels>(
    () => ({
      removeFile: t("removeFile"),
      statuses: {
        pending: t("attach"),
        uploading: t("uploading"),
        done: t("download"),
        error: t("uploadError"),
      },
      errors: {
        fileTooLarge: t("errorReason.fileTooLarge"),
        invalidRequest: t("errorReason.invalidRequest"),
        unauthorized: t("errorReason.unauthorized"),
        forbidden: t("errorReason.forbidden"),
        unsupportedType: t("errorReason.unsupportedType"),
        serverError: t("errorReason.serverError"),
        networkError: t("errorReason.networkError"),
        invalidResponse: t("errorReason.invalidResponse"),
        unknown: t("errorReason.unknown"),
      },
    }),
    [t],
  );
  const fadeWidth = rem(40);
  const maskImage = useMemo((): string => {
    if (overflowEdges.left && overflowEdges.right) {
      return `linear-gradient(to right, transparent 0, var(--mantine-color-black) ${fadeWidth}, var(--mantine-color-black) calc(100% - ${fadeWidth}), transparent 100%)`;
    }
    if (overflowEdges.left) {
      return `linear-gradient(to right, transparent 0, var(--mantine-color-black) ${fadeWidth}, var(--mantine-color-black) 100%)`;
    }
    if (overflowEdges.right) {
      return `linear-gradient(to right, var(--mantine-color-black) 0, var(--mantine-color-black) calc(100% - ${fadeWidth}), transparent 100%)`;
    }
    return "none";
  }, [fadeWidth, overflowEdges.left, overflowEdges.right]);

  return (
    <AttachmentPreviewBar
      labels={labels}
      maskImage={maskImage}
      pendingFiles={pendingFiles}
      previewUrls={previewUrls}
      scrollerRef={scrollerRef}
      onRemove={onRemove}
    />
  );
}
