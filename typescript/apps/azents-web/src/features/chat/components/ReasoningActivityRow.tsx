"use client";

import {
  Box,
  Collapse,
  Group,
  rem,
  ScrollArea,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconBubble, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useMemo, useRef } from "react";
import {
  activityDetailScrollbarSize,
  activityRowVerticalPadding,
} from "./activityRowPresentation";
import inlineControlClasses from "./ChatInlineControl.module.css";
import { chatCollapseTransitionProps } from "./collapsiblePresentation";
import { MarkdownContent } from "./MarkdownContent";
import classes from "./ReasoningActivityRow.module.css";
import type { KeyboardEvent, MouseEvent, ReactElement } from "react";

interface ReasoningActivityRowProps {
  reasoningSummary: string;
}

const HTML_COMMENT_PATTERN =
  /<!--[\s\S]*?-->|<!—[\s\S]*?(?:—>|-->)|<!--|-->|<!—|—>/gu;

function removeHtmlComments(content: string): string {
  return content.replace(HTML_COMMENT_PATTERN, "");
}

function markdownLineToPlainText(line: string): string {
  return line
    .replace(/^(?:`{3,}|~{3,})[^`~]*$/u, "")
    .replace(/^(?:\s*[-*_]){3,}\s*$/u, "")
    .replace(/^\s*[-+*]\s+\[[ xX]\]\s+/u, "")
    .replace(/^\s{0,3}(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)/u, "")
    .replace(/!\[([^\]]*)\]\([^)]*\)/gu, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/\[([^\]]+)\]\[[^\]]*\]/gu, "$1")
    .replace(/<\/?[A-Za-z][^>]*>/gu, "")
    .replace(/<([^>]+)>/gu, "$1")
    .replace(/(\*\*|__|~~)(.*?)\1/gu, "$2")
    .replace(/(^|\s)([*_])([^*_]+)\2(?=\s|[.,!?]|$)/gu, "$1$3")
    .replace(/`([^`]*)`/gu, "$1")
    .replace(/\\([\\`*_{}\[\]()#+\-.!>])/gu, "$1")
    .replace(/&nbsp;/gu, " ")
    .replace(/&amp;/gu, "&")
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&quot;/gu, '"')
    .replace(/&#39;|&apos;/gu, "'")
    .replace(/\s+/gu, " ")
    .trim();
}

function getThinkingPreview(reasoningSummary: string): string | null {
  const firstNonEmptyLine = removeHtmlComments(reasoningSummary)
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .find((line) => line.length > 0);

  if (!firstNonEmptyLine) {
    return null;
  }

  const preview = markdownLineToPlainText(firstNonEmptyLine);
  return preview.length > 0 ? preview : null;
}

function isElementVisibleInViewport(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect();
  const viewportHeight =
    window.innerHeight || document.documentElement.clientHeight;

  return rect.top >= 0 && rect.bottom <= viewportHeight;
}

export function ReasoningActivityRow({
  reasoningSummary,
}: ReasoningActivityRowProps): ReactElement {
  const t = useTranslations("chat");
  const headerRef = useRef<HTMLButtonElement>(null);
  const [opened, { close, toggle }] = useDisclosure(false);
  const sanitizedReasoningSummary = useMemo(
    () => removeHtmlComments(reasoningSummary).trim(),
    [reasoningSummary],
  );
  const preview = useMemo(
    () => getThinkingPreview(sanitizedReasoningSummary),
    [sanitizedReasoningSummary],
  );
  const canExpand = sanitizedReasoningSummary.length > 0;
  const label = opened || preview === null ? t("thinkingLabel") : preview;

  function collapseFromBody(): void {
    const shouldScrollToHeader = headerRef.current
      ? !isElementVisibleInViewport(headerRef.current)
      : false;

    close();

    if (shouldScrollToHeader) {
      requestAnimationFrame(() => {
        headerRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    }
  }

  function handleBodyClick(event: MouseEvent<HTMLDivElement>): void {
    const interactiveElement =
      event.target instanceof Element
        ? event.target.closest(
            'a, button, input, select, textarea, [role="button"]',
          )
        : null;

    if (interactiveElement && interactiveElement !== event.currentTarget) {
      return;
    }

    collapseFromBody();
  }

  function handleBodyKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (
      event.target !== event.currentTarget ||
      (event.key !== "Enter" && event.key !== " ")
    ) {
      return;
    }

    event.preventDefault();
    collapseFromBody();
  }

  const headerContent = (
    <>
      {canExpand ? (
        <IconChevronRight
          aria-hidden="true"
          size={14}
          className={classes.chevron}
          data-opened={opened}
          color="var(--mantine-color-dimmed)"
        />
      ) : null}
      <IconBubble
        aria-hidden="true"
        size={14}
        stroke={1.8}
        className={classes.icon}
      />
      <Text
        key={opened ? "opened" : "closed"}
        component="span"
        size="xs"
        c="dimmed"
        fw={500}
        className={`${classes.label} ${inlineControlClasses.label}`}
      >
        {label}
      </Text>
    </>
  );

  return (
    <Box py={activityRowVerticalPadding} w="100%" style={{ minWidth: 0 }}>
      {canExpand ? (
        <UnstyledButton
          ref={headerRef}
          className={classes.header}
          onClick={toggle}
          aria-expanded={opened}
        >
          <Group
            gap={rem(6)}
            wrap="nowrap"
            className={`${classes.headerContent} ${inlineControlClasses.root}`}
          >
            {headerContent}
          </Group>
        </UnstyledButton>
      ) : (
        <Group
          gap={rem(6)}
          wrap="nowrap"
          className={`${classes.header} ${inlineControlClasses.root}`}
        >
          {headerContent}
        </Group>
      )}
      {canExpand ? (
        <Collapse
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <ScrollArea.Autosize
            mah={rem(300)}
            mt={rem(4)}
            ml={rem(20)}
            scrollbarSize={activityDetailScrollbarSize}
          >
            <Box
              c="dimmed"
              role="button"
              tabIndex={0}
              aria-label={t("collapseThinking")}
              onClick={handleBodyClick}
              onKeyDown={handleBodyKeyDown}
              className={classes.body}
            >
              <MarkdownContent>{sanitizedReasoningSummary}</MarkdownContent>
            </Box>
          </ScrollArea.Autosize>
        </Collapse>
      ) : null}
    </Box>
  );
}
