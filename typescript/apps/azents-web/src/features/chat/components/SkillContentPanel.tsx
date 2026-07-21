import { Box, Paper, rem, ScrollArea } from "@mantine/core";
import { activityDetailScrollbarSize } from "./activityRowPresentation";
import { MarkdownContent } from "./MarkdownContent";
import classes from "./SkillLoadedActivityRow.module.css";
import type { ReactElement } from "react";

interface SkillContentPanelProps {
  content: string;
}

function stripMarkdownFrontmatter(content: string): string {
  const frontmatter = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/u.exec(
    content.replace(/^\uFEFF/u, ""),
  );
  return frontmatter === null || frontmatter.index !== 0
    ? content
    : content.slice(frontmatter[0].length).trimStart();
}

/** Shared Skill body presentation used by Skill events and load_skill calls. */
export function SkillContentPanel({
  content,
}: SkillContentPanelProps): ReactElement {
  const body = stripMarkdownFrontmatter(content);
  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      maw={rem(720)}
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
  );
}
