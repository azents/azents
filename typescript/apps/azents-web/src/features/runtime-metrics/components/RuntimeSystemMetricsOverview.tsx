"use client";

import {
  Alert,
  Badge,
  Box,
  Center,
  Group,
  Loader,
  Paper,
  rem,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { IconCpu, IconDatabase, IconServer2 } from "@tabler/icons-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  buildRuntimeMetricSparklineSegments,
  type RuntimeSystemMetricKey,
} from "../presentation";
import type { RuntimeSystemMetricsOverviewState } from "../types";
import type {
  AgentRuntimeSystemMetricCurrentResponse,
  AgentRuntimeSystemMetricsResponse,
  RuntimeSystemMetricsSummary,
  RuntimeSystemMetricState,
} from "@azents/public-client";

interface RuntimeSystemMetricsOverviewProps {
  state: RuntimeSystemMetricsOverviewState;
}

interface MetricDefinition {
  key: RuntimeSystemMetricKey;
  current: AgentRuntimeSystemMetricCurrentResponse;
  icon: React.ReactNode;
}

const SPARKLINE_WIDTH = 120;
const SPARKLINE_HEIGHT = 28;

function statusColor(
  state: RuntimeSystemMetricState | RuntimeSystemMetricsSummary,
): string {
  switch (state) {
    case "fresh":
      return "green";
    case "partial":
    case "stale":
    case "stopped":
      return "yellow";
    case "unavailable":
    case "disconnected":
      return "red";
    case "unsupported":
      return "gray";
  }
}

function formatBytes(value: number, locale: string): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let scaled = value;
  let unitIndex = 0;
  while (scaled >= 1024 && unitIndex < units.length - 1) {
    scaled /= 1024;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat(locale, {
    maximumFractionDigits: scaled >= 10 ? 1 : 2,
  }).format(scaled)} ${units[unitIndex]}`;
}

function formatCpu(value: number, locale: string, unit: string): string {
  const amount = new Intl.NumberFormat(locale, {
    maximumFractionDigits: 2,
  }).format(value / 1000);
  return `${amount} ${unit}`;
}

function formatMetricValue(
  metric: RuntimeSystemMetricKey,
  value: number,
  locale: string,
  cpuUnit: string,
): string {
  return metric === "cpu"
    ? formatCpu(value, locale, cpuUnit)
    : formatBytes(value, locale);
}

function MetricSparkline({
  metrics,
  metric,
}: {
  metrics: AgentRuntimeSystemMetricsResponse;
  metric: RuntimeSystemMetricKey;
}): React.ReactElement {
  const t = useTranslations("runtimeMetrics");
  const segments = buildRuntimeMetricSparklineSegments(
    metrics.samples,
    metric,
    SPARKLINE_WIDTH,
    SPARKLINE_HEIGHT,
  );
  if (segments.length === 0) {
    return (
      <Center h={rem(36)}>
        <Text c="dimmed" size="xs">
          {t("emptyTrend")}
        </Text>
      </Center>
    );
  }
  return (
    <Box
      component="svg"
      aria-label={t("trendLabel")}
      role="img"
      viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`}
      w="100%"
      h={rem(36)}
    >
      {segments.map((segment, segmentIndex) => {
        const points = segment
          .map((point) => `${point.x},${point.y}`)
          .join(" ");
        return (
          <g key={`${metric}-${segmentIndex}`}>
            {segment.length > 1 ? (
              <polyline
                fill="none"
                points={points}
                stroke="var(--mantine-color-blue-6)"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
              />
            ) : null}
            {segment.map((point, pointIndex) => (
              <circle
                key={`${metric}-${segmentIndex}-${pointIndex}`}
                cx={point.x}
                cy={point.y}
                fill="var(--mantine-color-blue-6)"
                r="1.5"
              />
            ))}
          </g>
        );
      })}
    </Box>
  );
}

function MetricPanel({
  definition,
  metrics,
}: {
  definition: MetricDefinition;
  metrics: AgentRuntimeSystemMetricsResponse;
}): React.ReactElement {
  const t = useTranslations("runtimeMetrics");
  const format = useFormatter();
  const locale = useLocale();
  const current = definition.current;
  const hasValue = current.used !== null;
  const percentage =
    current.percentage === null
      ? null
      : format.number(current.percentage, { maximumFractionDigits: 1 });
  const value =
    current.used === null
      ? t(`states.${current.state}`)
      : formatMetricValue(definition.key, current.used, locale, t("cpuUnit"));
  const total =
    current.total === null
      ? null
      : formatMetricValue(definition.key, current.total, locale, t("cpuUnit"));

  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <ThemeIcon color="blue" variant="light">
              {definition.icon}
            </ThemeIcon>
            <Stack gap={0}>
              <Text fw={650} size="sm">
                {t(`metrics.${definition.key}`)}
              </Text>
              <Text c="dimmed" size="xs">
                {current.measured_at
                  ? t("measuredAt", {
                      value: format.dateTime(new Date(current.measured_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                    })
                  : t("notMeasured")}
              </Text>
            </Stack>
          </Group>
          <Badge color={statusColor(current.state)} size="sm" variant="light">
            {t(`states.${current.state}`)}
          </Badge>
        </Group>
        <Stack gap={0}>
          <Text fw={700} size="xl">
            {percentage === null ? value : `${percentage}%`}
          </Text>
          <Text c="dimmed" size="xs">
            {hasValue && total ? t("usedOfTotal", { used: value, total }) : " "}
          </Text>
        </Stack>
        <MetricSparkline metric={definition.key} metrics={metrics} />
      </Stack>
    </Paper>
  );
}

export function RuntimeSystemMetricsOverview({
  state,
}: RuntimeSystemMetricsOverviewProps): React.ReactElement {
  const t = useTranslations("runtimeMetrics");

  if (state.type === "LOADING") {
    return (
      <Paper withBorder radius="md" p="md">
        <Center mih={rem(104)}>
          <Stack align="center" gap="xs">
            <Loader size="sm" />
            <Text c="dimmed" size="sm">
              {t("loading")}
            </Text>
          </Stack>
        </Center>
      </Paper>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="red" title={t("errorTitle")}>
        {state.message}
      </Alert>
    );
  }

  const { metrics } = state;
  const definitions: MetricDefinition[] = [
    {
      key: "cpu",
      current: metrics.cpu,
      icon: <IconCpu size={rem(18)} />,
    },
    {
      key: "memory",
      current: metrics.memory,
      icon: <IconServer2 size={rem(18)} />,
    },
    {
      key: "disk",
      current: metrics.disk,
      icon: <IconDatabase size={rem(18)} />,
    },
  ];

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start" gap="sm">
        <Stack gap={0}>
          <Text fw={700}>{t("title")}</Text>
          <Text c="dimmed" size="xs">
            {t("description")}
          </Text>
        </Stack>
        <Group gap="xs">
          {metrics.scope ? (
            <Badge color="blue" variant="light">
              {t("scope", { scope: t(`scopes.${metrics.scope}`) })}
            </Badge>
          ) : null}
          <Badge color={statusColor(metrics.summary)} variant="light">
            {t(`summaries.${metrics.summary}`)}
          </Badge>
        </Group>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
        {definitions.map((definition) => (
          <MetricPanel
            key={definition.key}
            definition={definition}
            metrics={metrics}
          />
        ))}
      </SimpleGrid>
    </Stack>
  );
}
