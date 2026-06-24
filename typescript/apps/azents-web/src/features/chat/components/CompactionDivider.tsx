"use client";

/**
 * Compaction summary divider.
 *
 * previous conversation summarytext notify and, collapse/expand with summary content display.
 * TurnDividerand similar dotted line style use.
 */

import { Box, Collapse, Group, Text, UnstyledButton } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { MarkdownContent } from "./MarkdownContent";

/** dotted line style */
const dashedLineStyle: React.CSSProperties = {
  flex: 1,
  borderBottom: "1px dashed var(--mantine-color-default-border)",
};

interface CompactionDividerProps {
  /** summary text (markdown) */
  content: string | null;
}

export function CompactionDivider({
  content,
}: CompactionDividerProps): React.ReactElement {
  const t = useTranslations("chat");
  const [opened, { toggle }] = useDisclosure(false);

  return (
    <Box mb="md">
      <Group gap="xs" align="center">
        <Box style={dashedLineStyle} />
        <Group gap={4} align="center">
          <Text size="xs" c="dimmed">
            {t("compaction.summary")}
          </Text>
          {content && (
            <UnstyledButton onClick={toggle}>
              <Group gap={2} align="center">
                <Text size="xs" c="dimmed" td="underline">
                  {opened ? t("compaction.collapse") : t("compaction.expand")}
                </Text>
                {opened ? (
                  <IconChevronDown
                    size={12}
                    color="var(--mantine-color-dimmed)"
                  />
                ) : (
                  <IconChevronRight
                    size={12}
                    color="var(--mantine-color-dimmed)"
                  />
                )}
              </Group>
            </UnstyledButton>
          )}
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
              border: "1px dashed var(--mantine-color-default-border)",
            }}
          >
            <MarkdownContent>{content}</MarkdownContent>
          </Box>
        </Collapse>
      )}
    </Box>
  );
}
