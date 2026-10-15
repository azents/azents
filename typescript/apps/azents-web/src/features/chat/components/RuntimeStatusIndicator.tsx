"use client";

/**
 * Runtime status indicator.
 *
 * chat during runtime totext/ready/error status display.
 */

import { Badge, Group, Loader, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useRuntimeStatusIndicator } from "../containers/useRuntimeStatusIndicator";
import type { RuntimeStatusIndicatorProps } from "../containers/useRuntimeStatusIndicator";

export function RuntimeStatusIndicatorView({
  status,
  visible,
}: RuntimeStatusIndicatorProps & {
  visible: boolean;
}): React.ReactElement | null {
  const t = useTranslations("chat.runtime");

  if (!visible) {
    return null;
  }

  if (status === "initializing") {
    return (
      <Group gap="xs" px="md" py={4}>
        <Loader size={14} />
        <Text size="xs" c="dimmed">
          {t("preparing")}
        </Text>
      </Group>
    );
  }

  if (status === "ready") {
    return (
      <Group gap="xs" px="md" py={4}>
        <Badge
          size="xs"
          variant="light"
          color="green"
          leftSection={<IconCheck size={10} />}
        >
          {t("ready")}
        </Badge>
      </Group>
    );
  }

  if (status === "error") {
    return (
      <Group gap="xs" px="md" py={4}>
        <Badge
          size="xs"
          variant="light"
          color="red"
          leftSection={<IconX size={10} />}
        >
          {t("error")}
        </Badge>
      </Group>
    );
  }

  return null;
}

export const RuntimeStatusIndicator = createReactContainer(
  "RuntimeStatusIndicator",
  useRuntimeStatusIndicator,
  RuntimeStatusIndicatorView,
);
