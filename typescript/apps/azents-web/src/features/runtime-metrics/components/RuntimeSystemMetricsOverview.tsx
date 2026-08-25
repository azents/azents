"use client";

import { AreaChart } from "@mantine/charts";
import {
  Alert,
  Badge,
  Center,
  Group,
  Loader,
  Paper,
  Progress,
  rem,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { IconCpu, IconDatabase, IconServer2 } from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import { formatLocalizedDate } from "@/shared/lib/date-format";
import { useLocale } from "@/shared/providers/locale";
import {
  buildRuntimeMetricChartData,
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

const SPARKLINE_SERIES: AreaChart.Series[] = [
  { name: "value", color: "blue.6" },
];

interface ReadableTrendScale {
  domain: [number, number];
  ticks: [number, number, number];
}

function buildReadableTrendScale(
  data: ReturnType<typeof buildRuntimeMetricChartData>,
): ReadableTrendScale {
  const values = data.flatMap((datum) =>
    datum.value === null ? [] : [datum.value],
  );
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = Math.max((maximum - minimum) * 0.25, 2);
  const lower = Math.floor(minimum - padding);
  const upper = Math.ceil(maximum + padding);
  const boundedLower = minimum >= 0 ? Math.max(0, lower) : lower;
  const boundedUpper = maximum <= 100 ? Math.min(100, upper) : upper;
  const midpoint = boundedLower + (boundedUpper - boundedLower) / 2;
  return {
    domain: [boundedLower, boundedUpper],
    ticks: [boundedLower, midpoint, boundedUpper],
  };
}

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

function MetricTrend({
  currentPercentage,
  metrics,
  metric,
}: {
  currentPercentage: number | null;
  metrics: AgentRuntimeSystemMetricsResponse;
  metric: RuntimeSystemMetricKey;
}): React.ReactElement {
  const t = useTranslations("runtimeMetrics");
  const format = useFormatter();
  const data = buildRuntimeMetricChartData(metrics.samples, metric);
  let trend: React.ReactElement;
  if (data.length === 0) {
    trend = (
      <Center h={rem(88)}>
        <Text c="dimmed" size="xs">
          {t("emptyTrend")}
        </Text>
      </Center>
    );
  } else {
    const readableScale = buildReadableTrendScale(data);
    trend = (
      <AreaChart
        aria-label={t("trendLabel")}
        areaChartProps={{
          margin: { top: 10, right: 4, bottom: 10, left: 4 },
        }}
        areaProps={{
          activeDot: false,
          dot: false,
          isAnimationActive: false,
        }}
        connectNulls={false}
        curveType="linear"
        data={data}
        dataKey="measuredAt"
        fillOpacity={0.2}
        gridAxis="x"
        gridProps={{ horizontal: true, vertical: false }}
        h={rem(88)}
        role="img"
        series={SPARKLINE_SERIES}
        strokeWidth={2}
        style={{ pointerEvents: "none" }}
        w="100%"
        withDots={false}
        withGradient
        withTooltip={false}
        withXAxis={false}
        withYAxis
        xAxisProps={{
          domain: ["dataMin", "dataMax"],
          padding: { left: 2, right: 2 },
          type: "number",
        }}
        yAxisProps={{
          allowDataOverflow: true,
          axisLine: false,
          domain: readableScale.domain,
          interval: 0,
          tickFormatter: (value: number) =>
            format.number(value, { maximumFractionDigits: 1 }),
          tickLine: false,
          tickMargin: 6,
          ticks: readableScale.ticks,
          width: 40,
        }}
      />
    );
  }

  return (
    <Stack gap="xs">
      {currentPercentage === null ? null : (
        <Progress
          aria-label={`${t(`metrics.${metric}`)} ${currentPercentage}%`}
          color="blue"
          radius="xl"
          size="sm"
          value={currentPercentage}
        />
      )}
      {trend}
    </Stack>
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
  const { locale } = useLocale();
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
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Group gap="sm" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
            <ThemeIcon color="blue" variant="light">
              {definition.icon}
            </ThemeIcon>
            <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
              <Text fw={650} size="sm">
                {t(`metrics.${definition.key}`)}
              </Text>
              <Text c="dimmed" size="xs">
                {current.measured_at
                  ? t("measuredAt", {
                      value: formatLocalizedDate(
                        new Date(current.measured_at),
                        locale,
                        {
                          dateStyle: "medium",
                          timeStyle: "short",
                        },
                      ),
                    })
                  : t("notMeasured")}
              </Text>
            </Stack>
          </Group>
          <Badge
            color={statusColor(current.state)}
            size="sm"
            variant="light"
            style={{ flexShrink: 0 }}
          >
            {t(`states.${current.state}`)}
          </Badge>
        </Group>
        <Stack gap={0}>
          <Text
            fw={700}
            size="xl"
            style={{
              fontFamily: "var(--font-geist-mono), monospace",
              fontVariantNumeric: "tabular-nums",
              overflowWrap: "anywhere",
            }}
          >
            {percentage === null ? value : `${percentage}%`}
          </Text>
          <Text
            c="dimmed"
            size="xs"
            style={{
              fontFamily: "var(--font-geist-mono), monospace",
              fontVariantNumeric: "tabular-nums",
              overflowWrap: "anywhere",
            }}
          >
            {hasValue && total ? t("usedOfTotal", { used: value, total }) : " "}
          </Text>
        </Stack>
        <MetricTrend
          currentPercentage={current.percentage}
          metric={definition.key}
          metrics={metrics}
        />
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
      <Group justify="space-between" align="flex-start" gap="sm" wrap="wrap">
        <Stack gap={0} style={{ flex: 1, minWidth: rem(180) }}>
          <Text fw={700}>{t("title")}</Text>
          <Text c="dimmed" size="xs">
            {t("description")}
          </Text>
        </Stack>
        <Group gap="xs" justify="flex-end" wrap="wrap">
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
      <SimpleGrid
        autoFlow="auto-fit"
        minColWidth={rem(220)}
        spacing="sm"
        type="container"
      >
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
