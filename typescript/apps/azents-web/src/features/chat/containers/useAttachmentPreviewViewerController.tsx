"use client";
import { useMediaQuery, useWindowEvent } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import {
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useRef,
} from "react";
import { formatFileSize } from "../components/FileAttachmentList";
type AttachmentPreviewContent =
  | {
      type: "image";
      url: string;
      altText: string;
    }
  | {
      type: "text";
      text: string;
    }
  | {
      type: "markdown";
      text: string;
    }
  | {
      type: "document-page";
      imageUrl: string;
      pageNumber: number;
    }
  | {
      type: "unsupported";
    };
interface AttachmentPreviewViewerProps {
  opened: boolean;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
  position?: {
    current: number;
    total: number;
  };
  name: string;
  mediaType: string;
  size?: number;
  downloadUrl: string;
  preview: AttachmentPreviewContent;
}
interface PointerOrigin {
  x: number;
  y: number;
}
const swipeThreshold = 48;
const wheelThreshold = 30;
const wheelCooldownMs = 400;
export interface AttachmentPreviewViewerViewProps {
  opened: AttachmentPreviewViewerProps["opened"];
  onClose: AttachmentPreviewViewerProps["onClose"];
  onPrevious?: AttachmentPreviewViewerProps["onPrevious"];
  onNext?: AttachmentPreviewViewerProps["onNext"];
  position?: AttachmentPreviewViewerProps["position"];
  name: AttachmentPreviewViewerProps["name"];
  size?: AttachmentPreviewViewerProps["size"];
  downloadUrl: AttachmentPreviewViewerProps["downloadUrl"];
  preview: AttachmentPreviewViewerProps["preview"];
  t: ReturnType<typeof useTranslations<"chat.attachment">>;
  isMobile: boolean;
  detail: string;
  imageUrl: string | null;
  imageAlt: string;
  handlePointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  handlePointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void;
  handleWheel: (event: ReactWheelEvent<HTMLDivElement>) => void;
  handlePreviewNative1: () => void;
  handlePreviewNative2: (
    event: React.MouseEvent<HTMLDivElement, MouseEvent>,
  ) => void;
}
export function useAttachmentPreviewViewerController({
  opened,
  onClose,
  onPrevious,
  onNext,
  position,
  name,
  mediaType,
  size,
  downloadUrl,
  preview,
}: AttachmentPreviewViewerProps): AttachmentPreviewViewerViewProps {
  const t = useTranslations("chat.attachment");
  const isMobile = useMediaQuery("(max-width: 48em)");
  const pointerOriginRef = useRef<PointerOrigin | null>(null);
  const swipedRef = useRef(false);
  const lastWheelNavigationAtRef = useRef(0);

  useWindowEvent("keydown", (event: KeyboardEvent): void => {
    if (!opened) {
      return;
    }
    if (event.key === "ArrowLeft" && onPrevious) {
      event.preventDefault();
      onPrevious();
    } else if (event.key === "ArrowRight" && onNext) {
      event.preventDefault();
      onNext();
    }
  });

  const detail = [mediaType, size == null ? null : formatFileSize(size)]
    .filter(Boolean)
    .join(" · ");
  const imageUrl =
    preview.type === "image"
      ? preview.url
      : preview.type === "document-page"
        ? preview.imageUrl
        : null;
  const imageAlt =
    preview.type === "image"
      ? preview.altText
      : preview.type === "document-page"
        ? `${name} page ${preview.pageNumber}`
        : "";

  const handlePointerDown = (
    event: ReactPointerEvent<HTMLDivElement>,
  ): void => {
    if (!event.isPrimary) {
      return;
    }
    pointerOriginRef.current = { x: event.clientX, y: event.clientY };
    swipedRef.current = false;
  };
  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>): void => {
    const origin = pointerOriginRef.current;
    pointerOriginRef.current = null;
    if (origin === null || !event.isPrimary) {
      return;
    }
    const deltaX = event.clientX - origin.x;
    const deltaY = event.clientY - origin.y;
    if (
      Math.abs(deltaX) < swipeThreshold ||
      Math.abs(deltaX) <= Math.abs(deltaY)
    ) {
      return;
    }
    swipedRef.current = true;
    if (deltaX > 0) {
      onPrevious?.();
    } else {
      onNext?.();
    }
  };
  const handleWheel = (event: ReactWheelEvent<HTMLDivElement>): void => {
    if (
      Math.abs(event.deltaX) < wheelThreshold ||
      Math.abs(event.deltaX) <= Math.abs(event.deltaY)
    ) {
      return;
    }
    event.preventDefault();
    const now = Date.now();
    if (now - lastWheelNavigationAtRef.current < wheelCooldownMs) {
      return;
    }
    lastWheelNavigationAtRef.current = now;
    if (event.deltaX > 0) {
      onNext?.();
    } else {
      onPrevious?.();
    }
  };

  function handlePreviewNative1(): void {
    pointerOriginRef.current = null;
  }

  function handlePreviewNative2(
    event: React.MouseEvent<HTMLDivElement, MouseEvent>,
  ): void {
    if (!swipedRef.current) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    swipedRef.current = false;
  }
  return {
    opened,
    onClose,
    onPrevious,
    onNext,
    position,
    name,
    size,
    downloadUrl,
    preview,
    t,
    isMobile,
    detail,
    imageUrl,
    imageAlt,
    handlePointerDown,
    handlePointerUp,
    handleWheel,
    handlePreviewNative1,
    handlePreviewNative2,
  };
}
