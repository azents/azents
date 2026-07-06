"use client";

import { Box, Grid, Group, rem, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";

function SystemBox({
  children,
  kind,
  title,
}: {
  children: React.ReactNode;
  kind: string;
  title: string;
}): React.ReactElement {
  return (
    <Box
      p="md"
      style={{
        background: "rgba(7, 10, 15, 0.72)",
        border: "1px solid rgba(148, 163, 184, 0.18)",
        borderRadius: rem(6),
      }}
    >
      <Stack gap="xs">
        <Text c="dimmed" ff="monospace" size="xs">
          {kind}
        </Text>
        <Text fw={700}>{title}</Text>
        <Text c="dimmed" lh={1.55} size="sm">
          {children}
        </Text>
      </Stack>
    </Box>
  );
}

function SignalLine({
  label,
  value,
}: {
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <Group
      gap="md"
      justify="space-between"
      py={rem(9)}
      style={{
        borderTop: "1px solid rgba(148, 163, 184, 0.12)",
      }}
      wrap="nowrap"
    >
      <Text c="dimmed" ff="monospace" size="xs">
        {label}
      </Text>
      <Text c="var(--mantine-color-dark-1)" ff="monospace" size="xs" ta="right">
        {value}
      </Text>
    </Group>
  );
}

export function ArchitectureDiagram(): React.ReactElement {
  const t = useTranslations("architecture.diagram");

  return (
    <Box
      aria-label={t("label")}
      role="img"
      style={{
        background: "#090e15",
        border: "1px solid rgba(148, 163, 184, 0.18)",
        borderRadius: rem(6),
        overflow: "hidden",
      }}
    >
      <Box
        p="md"
        style={{
          borderBottom: "1px solid rgba(148, 163, 184, 0.14)",
        }}
      >
        <Group justify="space-between" wrap="nowrap">
          <Text c="var(--mantine-color-dark-1)" ff="monospace" size="xs">
            {t("path")}
          </Text>
          <Text c="dimmed" ff="monospace" size="xs">
            {t("split")}
          </Text>
        </Group>
      </Box>

      <Box p="md">
        <Grid align="stretch" gap="sm">
          <Grid.Col span={{ base: 12, md: 4 }}>
            <SystemBox kind={t("team.kind")} title={t("team.title")}>
              {t("team.description")}
            </SystemBox>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <SystemBox kind={t("engine.kind")} title={t("engine.title")}>
              {t("engine.description")}
            </SystemBox>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <SystemBox kind={t("runtime.kind")} title={t("runtime.title")}>
              {t("runtime.description")}
            </SystemBox>
          </Grid.Col>
        </Grid>

        <Box
          mt="md"
          p="md"
          style={{
            background: "rgba(15, 23, 42, 0.54)",
            border: "1px solid rgba(148, 163, 184, 0.14)",
            borderRadius: rem(6),
          }}
        >
          <SignalLine
            label={t("signals.sessionLog.label")}
            value={t("signals.sessionLog.value")}
          />
          <SignalLine
            label={t("signals.handover.label")}
            value={t("signals.handover.value")}
          />
          <SignalLine
            label={t("signals.runtimeLease.label")}
            value={t("signals.runtimeLease.value")}
          />
          <SignalLine
            label={t("signals.boundary.label")}
            value={t("signals.boundary.value")}
          />
        </Box>
      </Box>
    </Box>
  );
}
