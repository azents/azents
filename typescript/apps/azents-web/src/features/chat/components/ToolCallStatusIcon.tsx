import { Box, Loader, rem } from "@mantine/core";
import {
  IconAlertCircle,
  IconCheck,
  IconHelpCircle,
  IconX,
} from "@tabler/icons-react";
import type { ReactElement } from "react";

export type ToolCallStatus =
  | "preparing"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "unknown";

interface ToolCallStatusIconProps {
  label: string;
  status: ToolCallStatus;
}

export function ToolCallStatusIcon({
  label,
  status,
}: ToolCallStatusIconProps): ReactElement {
  return (
    <Box
      component="span"
      role="img"
      aria-label={label}
      c={status === "failed" ? "red.5" : "dimmed"}
      style={{
        display: "inline-flex",
        flexShrink: 0,
        marginTop: rem(1),
        opacity: status === "failed" ? 0.75 : 1,
      }}
    >
      {status === "preparing" || status === "running" ? (
        <Loader
          aria-hidden="true"
          size={rem(16)}
          color="var(--mantine-color-dimmed)"
        />
      ) : status === "failed" ? (
        <IconAlertCircle aria-hidden="true" size={rem(16)} stroke={1.8} />
      ) : status === "completed" ? (
        <IconCheck aria-hidden="true" size={rem(16)} stroke={1.8} />
      ) : status === "cancelled" || status === "interrupted" ? (
        <IconX aria-hidden="true" size={rem(16)} stroke={1.8} />
      ) : (
        <IconHelpCircle aria-hidden="true" size={rem(16)} stroke={1.8} />
      )}
    </Box>
  );
}
