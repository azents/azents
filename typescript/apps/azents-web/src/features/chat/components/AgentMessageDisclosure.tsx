"use client";

import {
  Box,
  Collapse,
  Group,
  Paper,
  rem,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronRight, IconRobot } from "@tabler/icons-react";
import inlineControlClasses from "./ChatInlineControl.module.css";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import { MarkdownContent } from "./MarkdownContent";

interface AgentMessageDisclosureProps {
  title: string;
  titleTooltip?: string;
  content: string;
  actions?: React.ReactNode;
  opacity?: number;
}

export function AgentMessageDisclosure({
  title,
  titleTooltip = title,
  content,
  actions = null,
  opacity = 1,
}: AgentMessageDisclosureProps): React.ReactElement {
  const [opened, { toggle }] = useDisclosure(false);

  return (
    <Box mb="md" w="100%" opacity={opacity} style={{ minWidth: 0 }}>
      <Stack gap={rem(6)} maw={rem(720)}>
        <Group
          gap={rem(6)}
          c="dimmed"
          wrap="nowrap"
          role="button"
          tabIndex={0}
          aria-expanded={opened}
          aria-label={titleTooltip}
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
          <IconRobot aria-hidden="true" size={14} stroke={1.8} />
          <Tooltip label={titleTooltip} openDelay={500}>
            <Text
              size="xs"
              fw={600}
              lineClamp={1}
              className={inlineControlClasses.label}
              style={{ minWidth: 0 }}
            >
              {title}
            </Text>
          </Tooltip>
        </Group>
        <Collapse
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <Paper
            withBorder
            radius="md"
            p="sm"
            bg="var(--mantine-color-body)"
            style={{ minWidth: 0, overflow: "hidden" }}
          >
            <Box style={{ overflowWrap: "anywhere" }}>
              <MarkdownContent>{content}</MarkdownContent>
            </Box>
            {actions}
          </Paper>
        </Collapse>
      </Stack>
    </Box>
  );
}
