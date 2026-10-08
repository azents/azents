import { Code, rem, ScrollArea } from "@mantine/core";
import {
  activityDetailScrollAreaProps,
  activityDetailScrollbarSize,
} from "./activityRowPresentation";
import type { ReactElement } from "react";

export function ToolFailureOutput({
  output,
}: {
  output: string;
}): ReactElement {
  return (
    <ScrollArea.Autosize
      mah={rem(240)}
      scrollbars="y"
      scrollbarSize={activityDetailScrollbarSize}
      {...activityDetailScrollAreaProps}
    >
      <Code block style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
        {output}
      </Code>
    </ScrollArea.Autosize>
  );
}
