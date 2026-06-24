"use client";

/**
 * Runtime status indicator.
 *
 * chat during runtime totext/ready/error status display.
 */

import { Badge, Group, Loader, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type { RuntimeStatus } from "../types";

interface RuntimeStatusIndicatorProps {
  status: RuntimeStatus;
}

export function RuntimeStatusIndicator({
  status,
}: RuntimeStatusIndicatorProps): React.ReactElement | null {
  const t = useTranslations("chat.runtime");
  const [visible, setVisible] = useState(false);

  // ready status in 3sec after automatic hide
  useEffect(() => {
    if (status === "ready") {
      setVisible(true);
      const timer = setTimeout(() => setVisible(false), 3000);
      return () => clearTimeout(timer);
    }
    if (status === "initializing" || status === "error") {
      setVisible(true);
    } else {
      setVisible(false);
    }
  }, [status]);

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
