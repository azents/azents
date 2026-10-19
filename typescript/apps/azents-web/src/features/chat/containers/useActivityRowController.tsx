"use client";
import { useId, useRef, useState } from "react";
import { activityRowDetailInset } from "../../../shared/chat-presentation/components/activityRowPresentation";
import type { MantineSpacing } from "@mantine/core";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
interface ActivityRowProps {
  action?: ReactNode;
  ariaLabel: string;
  collapseFromDetail?: boolean;
  detail?: ReactNode;
  detailAriaLabel?: string;
  detailId?: string;
  detailInset?: MantineSpacing;
  expandedPrimary?: string;
  icon: ReactNode;
  primary: string;
  primaryTooltip?: string;
  disclosure?: { opened: boolean; onToggle: () => void };
  summaryDetail?: ReactNode;
  qualifier?: string | null;
  status?: ReactNode;
  subject?: string | null;
}
function isElementVisibleInViewport(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect();
  const viewportHeight =
    window.innerHeight || document.documentElement.clientHeight;
  return rect.top >= 0 && rect.bottom <= viewportHeight;
}
export interface ActivityRowViewProps {
  action: ActivityRowProps["action"];
  ariaLabel: ActivityRowProps["ariaLabel"];
  collapseFromDetail: boolean;
  detail: ActivityRowProps["detail"];
  detailAriaLabel: ActivityRowProps["detailAriaLabel"];
  detailInset: MantineSpacing;
  icon: ActivityRowProps["icon"];
  primaryTooltip: ActivityRowProps["primaryTooltip"];
  summaryDetail: ActivityRowProps["summaryDetail"];
  qualifier: string | null;
  status: ActivityRowProps["status"];
  subject: string | null;
  resolvedDetailId: string;
  opened: boolean;
  setOpened: (next: boolean) => void;
  headerRef: React.RefObject<HTMLButtonElement | null>;
  hasDetail: boolean;
  visiblePrimary: string;
  handleDetailClick: (event: MouseEvent<HTMLDivElement>) => void;
  handleDetailKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
}
export function useActivityRowController({
  action,
  ariaLabel,
  collapseFromDetail = false,
  detail,
  detailAriaLabel,
  detailId,
  detailInset = activityRowDetailInset,
  expandedPrimary,
  icon,
  primary,
  primaryTooltip,
  disclosure,
  summaryDetail,
  qualifier = null,
  status,
  subject = null,
}: ActivityRowProps): ActivityRowViewProps {
  const [internalOpened, setInternalOpened] = useState(false);
  const generatedDetailId = useId();
  const resolvedDetailId = detailId ?? generatedDetailId;
  const opened = disclosure?.opened ?? internalOpened;
  function setOpened(next: boolean): void {
    if (disclosure) {
      if (next !== opened) {
        disclosure.onToggle();
      }
    } else {
      setInternalOpened(next);
    }
  }
  const headerRef = useRef<HTMLButtonElement>(null);
  const hasDetail = detail !== null && typeof detail !== "undefined";
  const visiblePrimary = opened && expandedPrimary ? expandedPrimary : primary;

  function closeFromDetail(): void {
    const shouldScrollToHeader = headerRef.current
      ? !isElementVisibleInViewport(headerRef.current)
      : false;
    setOpened(false);
    headerRef.current?.focus({ preventScroll: true });
    if (shouldScrollToHeader) {
      requestAnimationFrame(() => {
        headerRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    }
  }

  function handleDetailClick(event: MouseEvent<HTMLDivElement>): void {
    if (!collapseFromDetail) {
      return;
    }
    const interactiveElement =
      event.target instanceof Element
        ? event.target.closest(
            'a, button, input, select, textarea, [role="button"]',
          )
        : null;
    if (interactiveElement && interactiveElement !== event.currentTarget) {
      return;
    }
    closeFromDetail();
  }

  function handleDetailKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (
      !collapseFromDetail ||
      event.target !== event.currentTarget ||
      (event.key !== "Enter" && event.key !== " ")
    ) {
      return;
    }
    event.preventDefault();
    closeFromDetail();
  }
  return {
    action,
    ariaLabel,
    collapseFromDetail,
    detail,
    detailAriaLabel,
    detailInset,
    icon,
    primaryTooltip,
    summaryDetail,
    qualifier,
    status,
    subject,
    resolvedDetailId,
    opened,
    setOpened,
    headerRef,
    hasDetail,
    visiblePrimary,
    handleDetailClick,
    handleDetailKeyDown,
  };
}
