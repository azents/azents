import { Box, rem } from "@mantine/core";
import { ChatDetailPanel } from "./ChatDetailPanel";
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
export function SkillContentBody({
  content,
}: SkillContentPanelProps): ReactElement {
  const body = stripMarkdownFrontmatter(content);
  return (
    <Box className={classes.body}>
      <MarkdownContent>{body}</MarkdownContent>
    </Box>
  );
}

export function SkillContentPanel(props: SkillContentPanelProps): ReactElement {
  return (
    <ChatDetailPanel maxHeight={rem(360)}>
      <SkillContentBody {...props} />
    </ChatDetailPanel>
  );
}
