import { Box, rem } from "@mantine/core";
import type { ReactElement, ReactNode } from "react";

interface StorybookCanvasProps {
  children: ReactNode;
  maxWidth?: string;
}

export function StorybookCanvas({
  children,
  maxWidth = rem(720),
}: StorybookCanvasProps): ReactElement {
  return (
    <Box p="lg" style={{ maxWidth, margin: "0 auto" }}>
      {children}
    </Box>
  );
}
