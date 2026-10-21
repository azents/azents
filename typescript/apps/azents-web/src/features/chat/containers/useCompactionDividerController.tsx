"use client";
import { useDisclosure } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRef } from "react";
interface CompactionDividerProps {
  /** Summary text rendered as Markdown. */
  content: string | null;
  /** Whether the summary starts expanded. */
  initialOpened?: boolean;
}
function isElementVisibleInViewport(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect();
  const viewportHeight =
    window.innerHeight || document.documentElement.clientHeight;

  return rect.top >= 0 && rect.bottom <= viewportHeight;
}
export interface CompactionDividerViewProps {
  content: CompactionDividerProps["content"];
  t: ReturnType<typeof useTranslations<"chat">>;
  toggleItemRef: React.RefObject<HTMLDivElement | null>;
  opened: boolean;
  toggle: () => void;
  collapseFromSummaryBody: () => void;
  handleSummaryBodyKeyDown: (
    event: React.KeyboardEvent<HTMLDivElement>,
  ) => void;
}
export function useCompactionDividerController({
  content,
  initialOpened = false,
}: CompactionDividerProps): CompactionDividerViewProps {
  const t = useTranslations("chat");
  const toggleItemRef = useRef<HTMLDivElement>(null);
  const [opened, { close, toggle }] = useDisclosure(initialOpened);

  function collapseFromSummaryBody(): void {
    const shouldScrollToToggle = toggleItemRef.current
      ? !isElementVisibleInViewport(toggleItemRef.current)
      : false;

    close();

    if (shouldScrollToToggle) {
      requestAnimationFrame(() => {
        toggleItemRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    }
  }

  function handleSummaryBodyKeyDown(
    event: React.KeyboardEvent<HTMLDivElement>,
  ): void {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }

    event.preventDefault();
    collapseFromSummaryBody();
  }
  return {
    content,
    t,
    toggleItemRef,
    opened,
    toggle,
    collapseFromSummaryBody,
    handleSummaryBodyKeyDown,
  };
}
