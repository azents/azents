"use client";

import {
  ActionIcon,
  Alert,
  Anchor,
  Box,
  Button,
  Group,
  Loader,
  Popover,
  Progress,
  rem,
  Skeleton,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconExternalLink,
  IconRefresh,
} from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { subscriptionUsageSummaryLimits } from "@/features/llm-settings/subscriptionUsage";
import { projectComposerSubscriptionIndicator } from "../composerSubscriptionUsage";
import type {
  SubscriptionUsageSnapshot,
  SubscriptionUsageState,
} from "@/features/llm-settings/subscriptionUsage";
import type {
  SubscriptionUsageAvailableResponse,
  SubscriptionUsageLimitResponse,
  SubscriptionUsageUnavailableReason,
} from "@azents/public-client";

interface ComposerSubscriptionUsageIndicatorProps {
  compact: boolean;
  onOpen: () => void;
  state: SubscriptionUsageState;
}

export function ComposerSubscriptionUsageIndicator({
  compact,
  onOpen,
  state,
}: ComposerSubscriptionUsageIndicatorProps): React.ReactElement | null {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const format = useFormatter();
  const indicator = projectComposerSubscriptionIndicator(state);

  if (indicator.type === "HIDDEN") {
    return null;
  }

  let label = t("title");
  let color: "gray" | "red" | "teal" | "yellow" = "gray";
  let content: React.ReactNode = null;

  switch (indicator.type) {
    case "LOADING":
      label = t("loading");
      content = <Loader size={rem(14)} />;
      break;
    case "PERCENT": {
      const percent = format.number(indicator.percent / 100, {
        maximumFractionDigits: 0,
        style: "percent",
      });
      label = `${t("title")}: ${indicator.label} ${percent}${
        indicator.stale ? ` · ${t("staleTitle")}` : ""
      }`;
      color = indicator.stale
        ? "yellow"
        : indicator.severity === "critical"
          ? "red"
          : indicator.severity === "warning"
            ? "yellow"
            : "teal";
      content = compact ? (
        <UsageRing percent={indicator.percent} color={color} />
      ) : (
        <Group gap={rem(5)} wrap="nowrap">
          <UsageRing percent={indicator.percent} color={color} />
          <Text component="span" size="xs" fw={600}>
            {percent}
          </Text>
        </Group>
      );
      break;
    }
    case "EXTERNAL":
      label = `${t("title")}: ${t("externalDescription")}${
        indicator.stale ? ` · ${t("staleTitle")}` : ""
      }`;
      color = indicator.stale ? "yellow" : "gray";
      content = <IconExternalLink size={rem(15)} />;
      break;
    case "UNAVAILABLE":
      label = `${t("title")}: ${t("unavailable")}`;
      content = <IconAlertTriangle size={rem(15)} />;
      break;
  }

  return (
    <Tooltip label={label} withArrow>
      <Button
        aria-label={label}
        color={color}
        onClick={onOpen}
        px={compact ? rem(8) : "xs"}
        radius={rem(12)}
        size="compact-sm"
        variant="subtle"
        style={{ minHeight: rem(36), minWidth: compact ? rem(36) : rem(58) }}
      >
        {content}
      </Button>
    </Tooltip>
  );
}

function UsageRing({
  color,
  percent,
}: {
  color: "gray" | "red" | "teal" | "yellow";
  percent: number;
}): React.ReactElement {
  const radius = 6;
  const circumference = 2 * Math.PI * radius;
  const normalized = Math.min(100, Math.max(0, percent));
  return (
    <Box
      component="svg"
      viewBox="0 0 16 16"
      aria-hidden="true"
      style={{ display: "block", height: rem(16), width: rem(16) }}
    >
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke="var(--mantine-color-default-border)"
        strokeWidth="3"
      />
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke={`var(--mantine-color-${color}-6)`}
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - normalized / 100)}
        strokeLinecap="round"
        strokeWidth="3"
        style={{ transform: "rotate(-90deg)", transformOrigin: "50% 50%" }}
      />
    </Box>
  );
}

interface ComposerSubscriptionUsagePopoverProps {
  compact: boolean;
  onRefresh: () => Promise<void> | void;
  state: SubscriptionUsageState;
}

export function ComposerSubscriptionUsagePopover({
  compact,
  onRefresh,
  state,
}: ComposerSubscriptionUsagePopoverProps): React.ReactElement | null {
  const [opened, setOpened] = useState(false);
  const indicator = projectComposerSubscriptionIndicator(state);

  if (indicator.type === "HIDDEN") {
    return null;
  }

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      shadow="md"
      width={rem(320)}
      withArrow
      withinPortal
    >
      <Popover.Target>
        <Box component="span" style={{ display: "inline-flex" }}>
          <ComposerSubscriptionUsageIndicator
            compact={compact}
            onOpen={() => setOpened((current) => !current)}
            state={state}
          />
        </Box>
      </Popover.Target>
      <Popover.Dropdown>
        <ComposerSubscriptionUsageDetails onRefresh={onRefresh} state={state} />
      </Popover.Dropdown>
    </Popover>
  );
}

interface ComposerSubscriptionUsageDetailsProps {
  onRefresh: () => Promise<void> | void;
  state: SubscriptionUsageState;
}

export function ComposerSubscriptionUsageDetails({
  onRefresh,
  state,
}: ComposerSubscriptionUsageDetailsProps): React.ReactElement | null {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");

  if (state.type === "IDLE" || state.type === "DISABLED") {
    return null;
  }

  return (
    <Stack aria-label={t("title")} gap="sm" role="region">
      {state.type === "LOADING" ? <LoadingDetails /> : null}
      {state.type === "AVAILABLE" ? (
        <AvailableDetails
          snapshot={state.snapshot}
          refreshing={state.refreshing}
          onRefresh={onRefresh}
        />
      ) : null}
      {state.type === "EXTERNAL" ? (
        <ExternalDetails
          snapshot={state.snapshot}
          refreshing={state.refreshing}
          onRefresh={onRefresh}
        />
      ) : null}
      {state.type === "UNAVAILABLE" ? (
        <UnavailableDetails
          reason={state.reason}
          retryable={state.retryable}
          onRefresh={onRefresh}
        />
      ) : null}
      {state.type === "STALE_ERROR" ? (
        <StaleDetails snapshot={state.snapshot} onRefresh={onRefresh} />
      ) : null}
    </Stack>
  );
}

function DetailsHeader({
  onRefresh,
  refreshing,
}: {
  onRefresh: () => Promise<void> | void;
  refreshing: boolean;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <Group justify="space-between" wrap="nowrap">
      <Text size="xs" fw={600}>
        {t("title")}
      </Text>
      <Tooltip label={t("refresh")}>
        <ActionIcon
          aria-label={t("refresh")}
          loading={refreshing}
          onClick={() => void onRefresh()}
          size="sm"
          variant="subtle"
        >
          <IconRefresh size={rem(14)} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}

function LoadingDetails(): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <Stack aria-live="polite" gap="xs">
      <Text size="xs" fw={600}>
        {t("title")}
      </Text>
      <Skeleton height={rem(8)} />
      <Skeleton height={rem(8)} width="70%" />
    </Stack>
  );
}

function AvailableDetails({
  onRefresh,
  refreshing,
  snapshot,
}: {
  onRefresh: () => Promise<void> | void;
  refreshing: boolean;
  snapshot: SubscriptionUsageAvailableResponse;
}): React.ReactElement {
  return (
    <Stack gap="sm">
      <DetailsHeader refreshing={refreshing} onRefresh={onRefresh} />
      <AvailableContent snapshot={snapshot} />
    </Stack>
  );
}

function AvailableContent({
  snapshot,
}: {
  snapshot: SubscriptionUsageAvailableResponse;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <Stack gap="sm">
      {snapshot.plan_label ? (
        <Text c="dimmed" size="xs">
          {t("plan", { plan: snapshot.plan_label })}
        </Text>
      ) : null}
      {subscriptionUsageSummaryLimits(snapshot).map((limit) => (
        <LimitRow key={limit.id} limit={limit} />
      ))}
      <Freshness fetchedAt={snapshot.fetched_at} />
    </Stack>
  );
}

function LimitRow({
  limit,
}: {
  limit: SubscriptionUsageLimitResponse;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const format = useFormatter();
  const percent = Math.min(100, Math.max(0, limit.used_percent));
  const formattedPercent = format.number(percent / 100, {
    maximumFractionDigits: 0,
    style: "percent",
  });
  const color = percent >= 90 ? "red" : percent >= 70 ? "yellow" : "teal";
  return (
    <Stack gap={rem(4)}>
      <Group justify="space-between" gap="sm" wrap="nowrap">
        <Text size="xs" truncate>
          {limit.label}
        </Text>
        <Text size="xs" fw={600}>
          {formattedPercent}
        </Text>
      </Group>
      <Progress
        aria-label={t("progressLabel", {
          label: limit.label,
          percent: formattedPercent,
        })}
        color={color}
        radius="xl"
        size="xs"
        value={percent}
      />
      <Text c="dimmed" size="xs">
        {limit.resets_at
          ? t("resetsAt", { value: formatDateTime(limit.resets_at, format) })
          : t("noReset")}
      </Text>
    </Stack>
  );
}

function ExternalDetails({
  onRefresh,
  refreshing,
  snapshot,
}: {
  onRefresh: () => Promise<void> | void;
  refreshing: boolean;
  snapshot: Extract<SubscriptionUsageSnapshot, { type: "external" }>;
}): React.ReactElement {
  return (
    <Stack gap="sm">
      <DetailsHeader refreshing={refreshing} onRefresh={onRefresh} />
      <ExternalContent snapshot={snapshot} />
    </Stack>
  );
}

function ExternalContent({
  snapshot,
}: {
  snapshot: Extract<SubscriptionUsageSnapshot, { type: "external" }>;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <Stack gap="xs">
      <Text c="dimmed" size="xs">
        {t("externalDescription")}
      </Text>
      <Anchor
        href={snapshot.url}
        rel="noopener noreferrer"
        target="_blank"
        size="xs"
      >
        <Group component="span" gap={rem(5)} wrap="nowrap">
          <span>{t("externalAction")}</span>
          <IconExternalLink aria-label={t("opensNewTab")} size={rem(13)} />
        </Group>
      </Anchor>
      <Freshness fetchedAt={snapshot.fetched_at} />
    </Stack>
  );
}

function UnavailableDetails({
  onRefresh,
  reason,
  retryable,
}: {
  onRefresh: () => Promise<void> | void;
  reason: SubscriptionUsageUnavailableReason | null;
  retryable: boolean;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <Alert
      color="gray"
      icon={<IconAlertTriangle size={rem(14)} />}
      title={t("unavailable")}
      variant="light"
    >
      <Stack gap="xs">
        <Text size="xs">{t(`reasons.${reason ?? "request_failed"}`)}</Text>
        {retryable ? (
          <Button
            onClick={() => void onRefresh()}
            size="compact-xs"
            variant="subtle"
          >
            {t("retry")}
          </Button>
        ) : null}
      </Stack>
    </Alert>
  );
}

function StaleDetails({
  onRefresh,
  snapshot,
}: {
  onRefresh: () => Promise<void> | void;
  snapshot: SubscriptionUsageSnapshot;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <Stack gap="sm">
      <Alert
        color="yellow"
        icon={<IconAlertTriangle size={rem(14)} />}
        title={t("staleTitle")}
        variant="light"
      >
        <Group justify="space-between" gap="sm" wrap="nowrap">
          <Text size="xs">{t("staleDescription")}</Text>
          <Button
            onClick={() => void onRefresh()}
            size="compact-xs"
            variant="subtle"
          >
            {t("retry")}
          </Button>
        </Group>
      </Alert>
      {snapshot.type === "available" ? (
        <AvailableContent snapshot={snapshot} />
      ) : (
        <ExternalContent snapshot={snapshot} />
      )}
    </Stack>
  );
}

function Freshness({ fetchedAt }: { fetchedAt: string }): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const format = useFormatter();
  return (
    <Text c="dimmed" size="xs">
      {t("fetchedAt", { value: formatDateTime(fetchedAt, format) })}
    </Text>
  );
}

function formatDateTime(
  value: string,
  format: ReturnType<typeof useFormatter>,
): string {
  return format.dateTime(new Date(value), {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
