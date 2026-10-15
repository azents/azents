"use client";
import { rem } from "@mantine/core";
import { useWindowEvent } from "@mantine/hooks";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  buildDownloadUrl,
  historyStateWithPreview,
  isFileAvailable,
  isImageFile,
  previewHistoryMarker,
  previewSelection,
} from "../fileAttachmentPresentation";
import type { FileAttachment } from "@azents/session-core/types";
import type {
  CSSProperties,
  MouseEventHandler,
  PointerEventHandler,
} from "react";
export interface FileAttachmentListProps {
  files: FileAttachment[];
  presentation?: "agent" | "compact";
}
interface OverflowMaskState {
  ref: React.RefObject<HTMLDivElement | null>;
  style: CSSProperties;
}
const fadeWidth = rem(40);
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

export function useAttachmentStrip(props: {
  files: FileAttachment[];
  onPreview: (file: FileAttachment) => void;
}): typeof props &
  OverflowMaskState & {
    onPointerDown: PointerEventHandler;
    onPointerMove: PointerEventHandler;
    onPointerUp: PointerEventHandler;
    onClickCapture: MouseEventHandler;
  } {
  const overflow = useOverflowMask();
  const pointerStartX = useRef<number | null>(null);
  const dragged = useRef(false);
  return {
    ...props,
    ...overflow,
    onPointerDown: (event): void => {
      pointerStartX.current = event.clientX;
      dragged.current = false;
    },
    onPointerMove: (event): void => {
      if (
        pointerStartX.current !== null &&
        Math.abs(event.clientX - pointerStartX.current) > 6
      ) {
        dragged.current = true;
      }
    },
    onPointerUp: (): void => {
      pointerStartX.current = null;
    },
    onClickCapture: (event): void => {
      if (dragged.current) {
        event.preventDefault();
        event.stopPropagation();
        dragged.current = false;
      }
    },
  };
}
export function useFileAttachmentList({
  files,
  presentation = "agent",
}: FileAttachmentListProps): FileAttachmentListProps & {
  prominentImages: FileAttachment[];
  compactFiles: FileAttachment[];
  previewSelections: ReturnType<typeof previewSelection>[];
  selectedIndex: number | null;
  openPreview: (file: FileAttachment) => void;
  closePreview: () => void;
  movePreview: (offset: -1 | 1) => void;
} {
  const viewerId = useId();
  const { prominentImages, compactFiles, previewFiles } = useMemo(() => {
    const nextProminentImages = files.filter(
      (file) =>
        isImageFile(file.mediaType) &&
        isFileAvailable(file) &&
        buildDownloadUrl(file) !== null,
    );
    const nextCompactFiles = files.filter(
      (file) => !nextProminentImages.includes(file),
    );
    const usesAgentGallery =
      presentation === "agent" && nextProminentImages.length > 0;
    return {
      prominentImages: nextProminentImages,
      compactFiles: nextCompactFiles,
      previewFiles: usesAgentGallery
        ? [...nextProminentImages, ...nextCompactFiles]
        : files,
    };
  }, [files, presentation]);
  const previewSelections = useMemo(
    () =>
      previewFiles.flatMap((file) => {
        const selection = previewSelection(file);
        return selection === null ? [] : [selection];
      }),
    [previewFiles],
  );
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const previewOpenerRef = useRef<HTMLElement | null>(null);
  const historyEntryActiveRef = useRef(false);
  const historyClosePendingRef = useRef(false);

  const restorePreviewOpener = useCallback((): void => {
    requestAnimationFrame(() => previewOpenerRef.current?.focus());
  }, []);
  const writePreviewHistory = useCallback(
    (index: number, mode: "push" | "replace"): void => {
      const state = historyStateWithPreview(viewerId, index);
      if (mode === "push") {
        window.history.pushState(state, "", window.location.href);
      } else {
        window.history.replaceState(state, "", window.location.href);
      }
    },
    [viewerId],
  );

  useWindowEvent("popstate", (event: PopStateEvent): void => {
    const marker = previewHistoryMarker(event.state);
    if (
      marker?.viewerId === viewerId &&
      Number.isInteger(marker.index) &&
      marker.index >= 0 &&
      marker.index < previewSelections.length
    ) {
      historyEntryActiveRef.current = true;
      historyClosePendingRef.current = false;
      setSelectedIndex(marker.index);
      return;
    }
    if (!historyEntryActiveRef.current) {
      return;
    }
    historyEntryActiveRef.current = false;
    historyClosePendingRef.current = false;
    setSelectedIndex(null);
    restorePreviewOpener();
  });

  const openPreview = useCallback(
    (file: FileAttachment): void => {
      const nextIndex = previewSelections.findIndex(
        (selection) => selection.file === file,
      );
      if (nextIndex < 0) {
        return;
      }
      if (document.activeElement instanceof HTMLElement) {
        previewOpenerRef.current = document.activeElement;
      }
      writePreviewHistory(
        nextIndex,
        historyEntryActiveRef.current ? "replace" : "push",
      );
      historyEntryActiveRef.current = true;
      historyClosePendingRef.current = false;
      setSelectedIndex(nextIndex);
    },
    [previewSelections, writePreviewHistory],
  );
  const closePreview = useCallback((): void => {
    if (historyEntryActiveRef.current) {
      if (historyClosePendingRef.current) {
        return;
      }
      historyClosePendingRef.current = true;
      window.history.back();
      return;
    }
    setSelectedIndex(null);
    restorePreviewOpener();
  }, [restorePreviewOpener]);
  const movePreview = useCallback(
    (offset: -1 | 1): void => {
      if (selectedIndex === null) {
        return;
      }
      const nextIndex = selectedIndex + offset;
      if (nextIndex < 0 || nextIndex >= previewSelections.length) {
        return;
      }
      writePreviewHistory(nextIndex, "replace");
      setSelectedIndex(nextIndex);
    },
    [previewSelections.length, selectedIndex, writePreviewHistory],
  );

  return {
    files,
    presentation,
    prominentImages,
    compactFiles,
    previewSelections,
    selectedIndex,
    openPreview,
    closePreview,
    movePreview,
  };
}
