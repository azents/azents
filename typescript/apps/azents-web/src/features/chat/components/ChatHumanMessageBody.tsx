import { Paper, rem } from "@mantine/core";
import type { ReactElement, ReactNode } from "react";

/** The same human bubble shape for submitted, pending and optimistic input. */
export function ChatHumanMessageBody({
  children,
  opacity = 1,
}: {
  children: ReactNode;
  opacity?: number;
}): ReactElement {
  return (
    <Paper
      px="sm"
      py="2xs"
      radius="lg"
      bg="blue.6"
      c="white"
      style={{
        width: "fit-content",
        maxWidth: "100%",
        minWidth: 0,
        overflowWrap: "anywhere",
        borderTopRightRadius: rem(4),
        marginLeft: "auto",
        opacity,
      }}
    >
      {children}
    </Paper>
  );
}
