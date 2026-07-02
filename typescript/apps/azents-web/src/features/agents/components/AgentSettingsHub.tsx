"use client";

/** Agent settings hub with grouped row navigation. */

import {
  Badge,
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
  IconBrain,
  IconChevronRight,
  IconRobot,
  IconSettings,
  IconShield,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { AgentResponse } from "@azents/public-client";

interface AgentSettingsHubProps {
  handle: string;
  agent: AgentResponse;
}

interface SettingsRow {
  href: string;
  icon: React.ReactNode;
  label: string;
  description: string;
  value: string | null;
  tone?: "default" | "danger";
}

interface SettingsSection {
  title: string;
  rows: SettingsRow[];
}

function SettingsRowItem({ row }: { row: SettingsRow }): React.ReactElement {
  const danger = row.tone === "danger";
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
          color={danger ? "red" : "gray"}
          size={rem(36)}
          radius="xl"
          style={{ flexShrink: 0 }}
        >
          {row.icon}
        </ThemeIcon>
        <Box style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs" wrap="nowrap">
            <Text fw={600} c={danger ? "red" : "inherit"} truncate>
              {row.label}
            </Text>
            {row.value && (
              <Badge variant="light" color={danger ? "red" : "gray"} size="sm">
                {row.value}
              </Badge>
            )}
          </Group>
          <Text size="sm" c="dimmed" truncate>
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

function SettingsSectionCard({
  section,
}: {
  section: SettingsSection;
}): React.ReactElement {
  return (
    <Stack gap="xs">
      <Text size="sm" fw={700} c="dimmed" tt="uppercase" px="xs">
        {section.title}
      </Text>
      <Paper withBorder radius="lg" p="xs">
        <Stack gap={0}>
          {section.rows.map((row, index) => (
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
  );
}

export function AgentSettingsHub({
  handle,
  agent,
}: AgentSettingsHubProps): React.ReactElement {
  const t = useTranslations("workspace.agents.settingsHub");
  const basePath = `/w/${handle}/agents/${agent.id}/settings`;

  const sections: SettingsSection[] = [
    {
      title: t("sections.customization"),
      rows: [
        {
          href: `${basePath}/profile`,
          icon: <IconRobot size={rem(18)} />,
          label: t("profile.label"),
          description: t("profile.description"),
          value: agent.enabled ? t("values.active") : t("values.inactive"),
        },
        {
          href: `${basePath}/model`,
          icon: <IconAdjustments size={rem(18)} />,
          label: t("model.label"),
          description: t("model.description"),
          value: agent.model_selection?.model_display_name ?? null,
        },
      ],
    },
    {
      title: t("sections.capabilities"),
      rows: [
        {
          href: `${basePath}/capabilities`,
          icon: <IconSettings size={rem(18)} />,
          label: t("capabilities.label"),
          description: t("capabilities.description"),
          value: agent.shell_enabled
            ? t("values.shellEnabled")
            : t("values.shellDisabled"),
        },
        {
          href: `${basePath}/memory`,
          icon: <IconBrain size={rem(18)} />,
          label: t("memory.label"),
          description: t("memory.description"),
          value: agent.memory_enabled
            ? t("values.enabled")
            : t("values.disabled"),
        },
      ],
    },
    {
      title: t("sections.access"),
      rows: [
        {
          href: `${basePath}/admins`,
          icon: <IconShield size={rem(18)} />,
          label: t("admins.label"),
          description: t("admins.description"),
          value: null,
        },
      ],
    },
    {
      title: t("sections.danger"),
      rows: [
        {
          href: `${basePath}/danger`,
          icon: <IconTrash size={rem(18)} />,
          label: t("danger.label"),
          description: t("danger.description"),
          value: null,
          tone: "danger",
        },
      ],
    },
  ];

  return (
    <Box style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
      <Stack gap="xl" p="md" maw={rem(860)} mx="auto" w="100%">
        <Stack gap={4} px="xs">
          <Text fw={700} size="xl">
            {t("title")}
          </Text>
          <Text size="sm" c="dimmed">
            {t("description")}
          </Text>
        </Stack>
        {sections.map((section) => (
          <SettingsSectionCard key={section.title} section={section} />
        ))}
      </Stack>
    </Box>
  );
}
