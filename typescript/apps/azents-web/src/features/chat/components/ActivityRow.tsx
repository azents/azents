"use client";

import {
  Box,
  Collapse,
  Group,
  rem,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronRight } from "@tabler/icons-react";
import { useId, useRef, useState } from "react";
import {
  activityRowChevronSize,
  activityRowDetailInset,
  activityRowIconSize,
  activityRowSummarySize,
  activityRowVerticalPadding,
} from "./activityRowPresentation";
import inlineControlClasses from "./ChatInlineControl.module.css";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import type { MantineSpacing } from "@mantine/core";
import type { KeyboardEvent, MouseEvent, ReactElement, ReactNode } from "react";

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

/** Canonical row shell for chat reasoning, skill, and tool activity. */
export function ActivityRow({
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
}: ActivityRowProps): ReactElement {
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

  const summary = (
    <Group
      data-chat-row-header
      gap={rem(6)}
      wrap="nowrap"
      miw={0}
      className={inlineControlClasses.root}
    >
      <IconChevronRight
        aria-hidden="true"
        size={activityRowChevronSize}
        stroke={1.8}
        color="var(--mantine-color-dimmed)"
        style={{
          flexShrink: 0,
          opacity: hasDetail ? 1 : 0,
          transform: opened ? "rotate(90deg)" : "none",
          transition: chatChevronTransition,
        }}
      />
      <Box
        data-chat-row-icon
        className={inlineControlClasses.icon}
        c="dimmed"
        w={rem(activityRowIconSize)}
        h={rem(16)}
        style={{
          alignItems: "center",
          display: "inline-flex",
          flexShrink: 0,
          justifyContent: "center",
        }}
      >
        {icon}
      </Box>
      <Group gap={rem(6)} flex={1} miw={0} wrap="nowrap">
        <Tooltip
          label={primaryTooltip ?? visiblePrimary}
          disabled={!primaryTooltip}
          openDelay={500}
        >
          <Text
            component="span"
            size={activityRowSummarySize}
            c="dimmed"
            fw={500}
            truncate
            className={inlineControlClasses.label}
            maw={subject === null ? "100%" : "50%"}
            style={{ flexShrink: subject === null ? 1 : 0 }}
          >
            {visiblePrimary}
          </Text>
        </Tooltip>
        {subject !== null ? (
          <Text
            component="span"
            size={activityRowSummarySize}
            c="dimmed"
            truncate
            flex={1}
            miw={0}
            className={inlineControlClasses.label}
          >
            {subject}
          </Text>
        ) : null}
        {qualifier !== null ? (
          <Text
            component="span"
            size={activityRowSummarySize}
            c="dimmed"
            truncate
            miw={0}
            className={inlineControlClasses.label}
            style={{ flexShrink: 1 }}
          >
            {qualifier}
          </Text>
        ) : null}
      </Group>
      {status}
    </Group>
  );

  return (
    <Box
      py={activityRowVerticalPadding}
      w="100%"
      data-activity-row
      style={{ minWidth: 0 }}
    >
      <Group gap={rem(4)} wrap="nowrap" align="center">
        {hasDetail ? (
          <UnstyledButton
            ref={headerRef}
            flex={1}
            miw={0}
            onClick={() => setOpened(!opened)}
            aria-expanded={opened}
            aria-controls={resolvedDetailId}
            aria-label={ariaLabel}
            {...(summaryDetail
              ? { "aria-describedby": `${resolvedDetailId}-summary` }
              : {})}
          >
            {summary}
            {summaryDetail ? (
              <Box
                id={`${resolvedDetailId}-summary`}
                pl={activityRowDetailInset}
                pt="xs"
              >
                {summaryDetail}
              </Box>
            ) : null}
          </UnstyledButton>
        ) : (
          <Box flex={1} miw={0} aria-label={ariaLabel}>
            {summary}
          </Box>
        )}
        {action}
      </Group>
      {hasDetail ? (
        <Collapse
          id={resolvedDetailId}
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <Box
            data-chat-row-detail
            pl={detailInset}
            pr="xs"
            pt="xs"
            {...(collapseFromDetail
              ? {
                  "aria-label": detailAriaLabel ?? "",
                  role: "button",
                  tabIndex: 0,
                }
              : {})}
            onClick={handleDetailClick}
            onKeyDown={handleDetailKeyDown}
          >
            {detail}
          </Box>
        </Collapse>
      ) : null}
    </Box>
  );
}
