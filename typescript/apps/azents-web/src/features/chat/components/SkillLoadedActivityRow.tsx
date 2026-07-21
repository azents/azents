"use client";

import {
  Box,
  Collapse,
  Group,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconBook, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import {
  activityDetailScrollbarSize,
  activityRowVerticalPadding,
} from "./activityRowPresentation";
import inlineControlClasses from "./ChatInlineControl.module.css";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import { MarkdownContent } from "./MarkdownContent";
import classes from "./SkillLoadedActivityRow.module.css";
import type { ReactElement } from "react";

interface SkillLoadedActivityRowProps {
  content: string;
  grouped?: boolean;
  name: string | null;
}

function stripMarkdownFrontmatter(content: string): string {
  const frontmatter = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/u.exec(
    content.replace(/^\uFEFF/u, ""),
  );
  if (frontmatter === null || frontmatter.index !== 0) {
    return content;
  }
  return content.slice(frontmatter[0].length).trimStart();
}

export function SkillLoadedActivityRow({
  content,
  grouped = false,
  name,
}: SkillLoadedActivityRowProps): ReactElement {
  const t = useTranslations("chat");
  const [opened, { toggle }] = useDisclosure(false);
  const body = useMemo(() => stripMarkdownFrontmatter(content), [content]);
  const displayName = name || t("skillLoaded.unknownSkill");

  return (
    <Box
      py={grouped ? activityRowVerticalPadding : 0}
      mb={grouped ? 0 : "md"}
      w="100%"
      style={{ minWidth: 0 }}
    >
      <Stack gap={rem(6)} maw={rem(720)}>
        <Group
          gap={rem(6)}
          c="dimmed"
          wrap="nowrap"
          role="button"
          tabIndex={0}
          aria-expanded={opened}
          className={inlineControlClasses.root}
          style={{ cursor: "pointer", userSelect: "none" }}
          onClick={toggle}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              toggle();
            }
          }}
        >
          <IconChevronRight
            aria-hidden="true"
            size={14}
            stroke={1.8}
            style={{
              transform: opened ? "rotate(90deg)" : "none",
              transition: chatChevronTransition,
            }}
          />
          <IconBook aria-hidden="true" size={14} stroke={1.8} />
          <Text
            size="xs"
            fw={600}
            lineClamp={1}
            className={inlineControlClasses.label}
            style={{ minWidth: 0 }}
          >
            {t("skillLoaded.title", { name: displayName })}
          </Text>
        </Group>
        <Collapse
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <Box ml={rem(20)}>
            <Paper
              withBorder
              radius="md"
              p="sm"
              bg="var(--mantine-color-body)"
              style={{ minWidth: 0, overflow: "hidden" }}
            >
              <ScrollArea.Autosize
                mah={rem(360)}
                scrollbars="y"
                scrollbarSize={activityDetailScrollbarSize}
                style={{ maxWidth: "100%" }}
              >
                <Box className={classes.body}>
                  <MarkdownContent>{body}</MarkdownContent>
                </Box>
              </ScrollArea.Autosize>
            </Paper>
          </Box>
        </Collapse>
      </Stack>
    </Box>
  );
}
