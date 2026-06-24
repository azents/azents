"use client";

/** Chat UI in shared copy button. */

import { ActionIcon, CopyButton, Tooltip } from "@mantine/core";
import { IconCheck, IconCopy } from "@tabler/icons-react";

interface ChatCopyButtonProps {
  /** text to copy */
  value: string;
  /** default tooltip text */
  copyLabel: string;
  /** copy success tooltip text */
  copiedLabel: string;
  /** tooltip position */
  position?: "top" | "right" | "bottom" | "left";
  /** button size */
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  /** icon size */
  iconSize?: number;
}

export function ChatCopyButton({
  value,
  copyLabel,
  copiedLabel,
  position = "top",
  size = "sm",
  iconSize = 14,
}: ChatCopyButtonProps): React.ReactElement {
  return (
    <CopyButton value={value} timeout={1600}>
      {({ copied, copy }) => (
        <Tooltip
          label={copied ? copiedLabel : copyLabel}
          withArrow
          position={position}
          opened={copied}
        >
          <ActionIcon
            variant="subtle"
            color="gray"
            size={size}
            aria-label={copyLabel}
            onClick={copy}
          >
            {copied ? (
              <IconCheck size={iconSize} />
            ) : (
              <IconCopy size={iconSize} />
            )}
          </ActionIcon>
        </Tooltip>
      )}
    </CopyButton>
  );
}
