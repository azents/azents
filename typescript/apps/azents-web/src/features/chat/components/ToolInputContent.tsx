import { Box, Code, rem, ScrollArea, Stack, Text } from "@mantine/core";
import { toolInputPresentation } from "../toolInputPresentation";
import {
  activityDetailScrollAreaProps,
  activityDetailScrollbarSize,
} from "./activityRowPresentation";
import type { ReactElement } from "react";

export function ToolInputContent({ input }: { input: string }): ReactElement {
  const presentation = toolInputPresentation(input);
  const valueStyle = {
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  } as const;
  if (presentation.type === "text" || presentation.fields.length === 0) {
    return (
      <ScrollArea.Autosize
        mah={rem(240)}
        scrollbarSize={activityDetailScrollbarSize}
        {...activityDetailScrollAreaProps}
      >
        <Code block style={valueStyle}>
          {presentation.type === "text" ? presentation.text : "{}"}
        </Code>
      </ScrollArea.Autosize>
    );
  }
  return (
    <Stack component="dl" gap="sm" m={0}>
      {presentation.fields.map((field, index) => (
        <Box key={`${index}:${field.name}`}>
          <Text
            component="dt"
            size="xs"
            fw={600}
            ff="monospace"
            mb={rem(4)}
            style={{ overflowWrap: "anywhere" }}
          >
            {field.name}
          </Text>
          <Box component="dd" m={0}>
            <ScrollArea.Autosize
              mah={rem(240)}
              scrollbarSize={activityDetailScrollbarSize}
              {...activityDetailScrollAreaProps}
            >
              <Code block style={valueStyle}>
                {field.text}
              </Code>
            </ScrollArea.Autosize>
          </Box>
        </Box>
      ))}
    </Stack>
  );
}
