"use client";

/** Runtime activation CTA component. */
import { Button, Center, Loader, Stack, Text, ThemeIcon } from "@mantine/core";
import { IconPlayerPlay, IconTerminal2 } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

interface RuntimeActivationViewProps {
  canStartRuntime: boolean;
  isStarting: boolean;
  onStartRuntime: () => void;
}

export function RuntimeActivationView({
  canStartRuntime,
  isStarting,
  onStartRuntime,
}: RuntimeActivationViewProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  return (
    <Center h="100%" p="lg">
      <Stack align="center" gap="md" ta="center">
        <ThemeIcon size="xl" radius="xl" variant="light">
          <IconTerminal2 size="1.25rem" />
        </ThemeIcon>
        <Stack gap="xs">
          <Text fw={600}>{t("inactiveTitle")}</Text>
          <Text size="sm" c="dimmed">
            {t("inactiveDescription")}
          </Text>
        </Stack>
        <Button
          leftSection={
            isStarting ? <Loader size="xs" /> : <IconPlayerPlay size="1rem" />
          }
          onClick={onStartRuntime}
          disabled={!canStartRuntime || isStarting}
        >
          {isStarting ? t("startingRuntime") : t("startRuntime")}
        </Button>
      </Stack>
    </Center>
  );
}
