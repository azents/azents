"use client";

/**
 * Compaction summary divider.
 *
 * Shows when previous conversation turns were summarized and lets users expand
 * or collapse the generated summary inline.
 */

import { Box, Collapse, Group, rem, Text, UnstyledButton } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { MarkdownContent } from "./MarkdownContent";

const dashedLineStyle: React.CSSProperties = {
  flex: 1,
  borderBottom: `${rem(1)} dashed var(--mantine-color-default-border)`,
};

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
      <Group gap={rem(2)} align="center">
        <Text size="xs" c="dimmed" td="underline">
          {opened ? t("compaction.collapse") : t("compaction.expand")}
        </Text>
        {opened ? (
          <IconChevronDown size={rem(12)} color="var(--mantine-color-dimmed)" />
        ) : (
          <IconChevronRight
            size={rem(12)}
            color="var(--mantine-color-dimmed)"
          />
        )}
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
  const [opened, { toggle }] = useDisclosure(initialOpened);

  return (
    <Box mb="md">
      <Group gap="xs" align="center">
        <Box style={dashedLineStyle} />
        <Group gap="xs" align="center">
          <Text size="xs" c="dimmed">
            {t("compaction.summary")}
          </Text>
          {content && <SummaryToggleButton opened={opened} onToggle={toggle} />}
        </Group>
        <Box style={dashedLineStyle} />
      </Group>
      {content && (
        <Collapse expanded={opened}>
          <Box
            mt="xs"
            p="sm"
            style={{
              borderRadius: "var(--mantine-radius-sm)",
              background: "var(--mantine-color-default)",
              border: `${rem(1)} dashed var(--mantine-color-default-border)`,
            }}
          >
            <MarkdownContent>{content}</MarkdownContent>
            <Group justify="center" mt="sm">
              <SummaryToggleButton opened={opened} onToggle={toggle} />
            </Group>
          </Box>
        </Collapse>
      )}
    </Box>
  );
}
