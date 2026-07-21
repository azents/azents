"use client";

import { Box, Collapse, Group, rem, Text, UnstyledButton } from "@mantine/core";
import { IconChevronRight } from "@tabler/icons-react";
import { useRef, useState } from "react";
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
import type { KeyboardEvent, MouseEvent, ReactElement, ReactNode } from "react";

interface ActivityRowProps {
  action?: ReactNode;
  ariaLabel: string;
  collapseFromDetail?: boolean;
  detail?: ReactNode;
  detailAriaLabel?: string;
  expandedPrimary?: string;
  icon: ReactNode;
  primary: string;
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
  expandedPrimary,
  icon,
  primary,
  qualifier = null,
  status,
  subject = null,
}: ActivityRowProps): ReactElement {
  const [opened, setOpened] = useState(false);
  const headerRef = useRef<HTMLButtonElement>(null);
  const hasDetail = detail !== null && typeof detail !== "undefined";
  const visiblePrimary = opened && expandedPrimary ? expandedPrimary : primary;

  function closeFromDetail(): void {
    const shouldScrollToHeader = headerRef.current
      ? !isElementVisibleInViewport(headerRef.current)
      : false;
    setOpened(false);
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
      gap={rem(6)}
      wrap="nowrap"
      miw={0}
      className={inlineControlClasses.root}
    >
      <IconChevronRight
        aria-hidden="true"
        size={activityRowChevronSize}
        color="var(--mantine-color-dimmed)"
        style={{
          flexShrink: 0,
          opacity: hasDetail ? 1 : 0,
          transform: opened ? "rotate(90deg)" : "none",
          transition: chatChevronTransition,
        }}
      />
      <Box
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
        <Text
          component="span"
          size={activityRowSummarySize}
          c="dimmed"
          fw={500}
          truncate
          className={inlineControlClasses.label}
          style={{ flexShrink: subject === null ? 1 : 0 }}
        >
          {visiblePrimary}
        </Text>
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
            onClick={() => setOpened((value) => !value)}
            aria-expanded={opened}
            aria-label={ariaLabel}
          >
            {summary}
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
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <Box
            pl={activityRowDetailInset}
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
