"use client";

/** Workspace settings overview with focused settings-area navigation. */

import {
  Box,
  Group,
  Paper,
  rem,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
} from "@mantine/core";
import {
  IconAdjustments,
  IconChevronRight,
  IconPlugConnected,
  IconServer,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

interface WorkspaceSettingsHubProps {
  handle: string;
}

interface SettingsRow {
  href: string;
  icon: React.ReactNode;
  label: string;
  description: string;
}

function SettingsRowItem({ row }: { row: SettingsRow }): React.ReactElement {
  return (
    <UnstyledButton
      component={Link}
      href={row.href}
      w="100%"
      px="md"
      py="sm"
      style={{
        display: "block",
        borderRadius: "var(--mantine-radius-md)",
      }}
    >
      <Group gap="md" wrap="nowrap">
        <ThemeIcon
          variant="light"
          color="gray"
          size={rem(36)}
          radius="xl"
          style={{ flexShrink: 0 }}
        >
          {row.icon}
        </ThemeIcon>
        <Box style={{ flex: 1, minWidth: 0 }}>
          <Text fw={600} truncate>
            {row.label}
          </Text>
          <Text size="sm" c="dimmed">
            {row.description}
          </Text>
        </Box>
        <IconChevronRight
          size={rem(18)}
          color="var(--mantine-color-dimmed)"
          style={{ flexShrink: 0 }}
        />
      </Group>
    </UnstyledButton>
  );
}

export function WorkspaceSettingsHub({
  handle,
}: WorkspaceSettingsHubProps): React.ReactElement {
  const t = useTranslations("workspace.settings.hub");
  const basePath = `/w/${handle}/settings`;
  const rows: SettingsRow[] = [
    {
      href: `${basePath}/models`,
      icon: <IconAdjustments size={rem(18)} />,
      label: t("models.label"),
      description: t("models.description"),
    },
    {
      href: `${basePath}/llm-integrations`,
      icon: <IconPlugConnected size={rem(18)} />,
      label: t("llmIntegrations.label"),
      description: t("llmIntegrations.description"),
    },
    {
      href: `${basePath}/runtime-profiles`,
      icon: <IconServer size={rem(18)} />,
      label: t("runtimeProfiles.label"),
      description: t("runtimeProfiles.description"),
    },
  ];

  return (
    <Box style={{ height: "100%", overflow: "auto", minHeight: 0 }}>
      <Stack gap="xl" p="md" maw={rem(860)} mx="auto" w="100%">
        <Stack gap={4} px="xs">
          <Text fw={700} size="xl">
            {t("title")}
          </Text>
          <Text size="sm" c="dimmed">
            {t("description")}
          </Text>
        </Stack>
        <Stack gap="xs">
          <Text size="sm" fw={700} c="dimmed" tt="uppercase" px="xs">
            {t("configuration")}
          </Text>
          <Paper withBorder radius="lg" p="xs">
            <Stack gap={0}>
              {rows.map((row, index) => (
                <Box
                  key={row.href}
                  style={{
                    borderTop:
                      index === 0
                        ? "0 solid transparent"
                        : "0.0625rem solid var(--mantine-color-default-border)",
                  }}
                >
                  <SettingsRowItem row={row} />
                </Box>
              ))}
            </Stack>
          </Paper>
        </Stack>
      </Stack>
    </Box>
  );
}
