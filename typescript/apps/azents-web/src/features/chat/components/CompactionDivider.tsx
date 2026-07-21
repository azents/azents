"use client";

/**
 * Compaction summary divider.
 *
 * Shows when previous conversation turns were summarized and lets users expand
 * or collapse the generated summary inline.
 */

import { Box, Collapse, Group, rem, Text, UnstyledButton } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useRef } from "react";
import inlineControlClasses from "./ChatInlineControl.module.css";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
  chatCollapsibleChevronSize,
} from "./collapsiblePresentation";
import { MarkdownContent } from "./MarkdownContent";

const dashedLineStyle: React.CSSProperties = {
  flex: 1,
  borderBottom: `${rem(1)} dashed var(--mantine-color-default-border)`,
};

function isElementVisibleInViewport(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect();
  const viewportHeight =
    window.innerHeight || document.documentElement.clientHeight;

  return rect.top >= 0 && rect.bottom <= viewportHeight;
}

interface SummaryToggleButtonProps {
  opened: boolean;
  onToggle: () => void;
}

function SummaryToggleButton({
  opened,
  onToggle,
}: SummaryToggleButtonProps): React.ReactElement {
  const t = useTranslations("chat");

  return (
    <UnstyledButton aria-expanded={opened} onClick={onToggle}>
      <Group gap={rem(4)} className={inlineControlClasses.root}>
        <Text
          size="xs"
          c="dimmed"
          td="underline"
          className={inlineControlClasses.label}
        >
          {opened ? t("compaction.collapse") : t("compaction.expand")}
        </Text>
        <IconChevronRight
          size={chatCollapsibleChevronSize}
          color="var(--mantine-color-dimmed)"
          style={{
            transform: opened ? "rotate(90deg)" : "none",
            transition: chatChevronTransition,
          }}
        />
      </Group>
    </UnstyledButton>
  );
}

interface CompactionDividerProps {
  /** Summary text rendered as Markdown. */
  content: string | null;
  /** Whether the summary starts expanded. */
  initialOpened?: boolean;
}

export function CompactionDivider({
  content,
  initialOpened = false,
}: CompactionDividerProps): React.ReactElement {
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

  return (
    <Box mb="md">
      <Group gap="xs" align="center">
        <Box style={dashedLineStyle} />
        <Group ref={toggleItemRef} gap="xs" align="center">
          <Text size="xs" c="dimmed">
            {t("compaction.summary")}
          </Text>
          {content && <SummaryToggleButton opened={opened} onToggle={toggle} />}
        </Group>
        <Box style={dashedLineStyle} />
      </Group>
      {content && (
        <Collapse
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <Box
            mt="xs"
            p="sm"
            role="button"
            tabIndex={0}
            aria-label={t("compaction.collapse")}
            onClick={collapseFromSummaryBody}
            onKeyDown={handleSummaryBodyKeyDown}
            style={{
              borderRadius: "var(--mantine-radius-sm)",
              background: "var(--mantine-color-default)",
              border: `${rem(1)} dashed var(--mantine-color-default-border)`,
              cursor: "pointer",
            }}
          >
            <MarkdownContent>{content}</MarkdownContent>
          </Box>
        </Collapse>
      )}
    </Box>
  );
}
