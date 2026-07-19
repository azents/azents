"use client";

import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Collapse,
  Divider,
  Group,
  Progress,
  rem,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronUp,
  IconExternalLink,
  IconRefresh,
} from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import {
  subscriptionUsageAdditionalLimits,
  subscriptionUsageProgressColor,
  subscriptionUsageSummaryLimits,
} from "../subscriptionUsage";
import type {
  SubscriptionUsageSnapshot,
  SubscriptionUsageState,
} from "../subscriptionUsage";
import type {
  SubscriptionUsageAvailableResponse,
  SubscriptionUsageLimitResponse,
  SubscriptionUsageUnavailableReason,
} from "@azents/public-client";

export interface SubscriptionUsageSummaryProps {
  state: SubscriptionUsageState;
  onRefresh: () => Promise<void> | void;
}

export function SubscriptionUsageSummary({
  state,
  onRefresh,
}: SubscriptionUsageSummaryProps): React.ReactElement | null {
  switch (state.type) {
    case "IDLE":
      return null;
    case "DISABLED":
      return <DisabledUsage />;
    case "LOADING":
      return <LoadingUsage />;
    case "AVAILABLE":
      return (
        <AvailableUsage
          snapshot={state.snapshot}
          refreshing={state.refreshing}
          onRefresh={onRefresh}
        />
      );
    case "EXTERNAL":
      return (
        <ExternalUsage
          snapshot={state.snapshot}
          refreshing={state.refreshing}
          onRefresh={onRefresh}
        />
      );
    case "UNAVAILABLE":
      return (
        <UnavailableUsage
          reason={state.reason}
          retryable={state.retryable}
          onRefresh={onRefresh}
        />
      );
    case "STALE_ERROR":
      return <StaleUsage snapshot={state.snapshot} onRefresh={onRefresh} />;
  }
}

function UsageHeader({
  refreshing,
  onRefresh,
}: {
  refreshing: boolean;
  onRefresh: () => Promise<void> | void;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");

  return (
    <Group justify="space-between" wrap="nowrap">
      <Text fw={600} size="sm">
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
          <IconRefresh size={rem(16)} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}

function LoadingUsage(): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");

  return (
    <UsageSection ariaLabel={t("loading")}>
      <Stack gap="sm" aria-live="polite">
        <Group justify="space-between">
          <Skeleton height={rem(16)} width="30%" />
          <Skeleton height={rem(16)} width={rem(24)} />
        </Group>
        <Skeleton height={rem(10)} />
        <Skeleton height={rem(10)} width="70%" />
      </Stack>
    </UsageSection>
  );
}

function DisabledUsage(): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");

  return (
    <UsageSection ariaLabel={t("title")}>
      <Text c="dimmed" size="sm">
        {t("disabled")}
      </Text>
    </UsageSection>
  );
}

function AvailableUsage({
  snapshot,
  refreshing,
  onRefresh,
}: {
  snapshot: SubscriptionUsageAvailableResponse;
  refreshing: boolean;
  onRefresh: () => Promise<void> | void;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <UsageSection ariaLabel={t("title")}>
      <Stack gap="sm">
        <UsageHeader refreshing={refreshing} onRefresh={onRefresh} />
        <AvailableUsageContent snapshot={snapshot} />
      </Stack>
    </UsageSection>
  );
}

function AvailableUsageContent({
  snapshot,
}: {
  snapshot: SubscriptionUsageAvailableResponse;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const [additionalOpened, setAdditionalOpened] = useState(false);
  const [financialOpened, setFinancialOpened] = useState(false);
  const summaryLimits = subscriptionUsageSummaryLimits(snapshot);
  const additionalLimits = subscriptionUsageAdditionalLimits(snapshot);

  return (
    <Stack gap="sm">
      {snapshot.plan_label ? (
        <Text c="dimmed" size="xs">
          {t("plan", { plan: snapshot.plan_label })}
        </Text>
      ) : null}
      {summaryLimits.map((limit) => (
        <SubscriptionUsageLimitRow key={limit.id} limit={limit} />
      ))}
      {additionalLimits.length > 0 ? (
        <DisclosureButton
          label={t("additionalLimits", { count: additionalLimits.length })}
          opened={additionalOpened}
          onClick={() => setAdditionalOpened((value) => !value)}
        />
      ) : null}
      <Collapse expanded={additionalOpened}>
        <Stack gap="sm" pt="xs">
          {additionalLimits.map((limit) => (
            <SubscriptionUsageLimitRow key={limit.id} limit={limit} />
          ))}
        </Stack>
      </Collapse>
      <Freshness fetchedAt={snapshot.fetched_at} />
      {snapshot.financial_details ? (
        <>
          <DisclosureButton
            label={t("financialDetails")}
            opened={financialOpened}
            onClick={() => setFinancialOpened((value) => !value)}
          />
          <Collapse expanded={financialOpened}>
            <FinancialDetails
              details={snapshot.financial_details}
              planLabel={snapshot.plan_label}
            />
          </Collapse>
        </>
      ) : null}
    </Stack>
  );
}

function SubscriptionUsageLimitRow({
  limit,
}: {
  limit: SubscriptionUsageLimitResponse;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const format = useFormatter();
  const usedPercent = Math.min(100, Math.max(0, limit.used_percent));
  const formattedPercent = format.number(usedPercent / 100, {
    maximumFractionDigits: 1,
    style: "percent",
  });

  return (
    <Stack gap={rem(6)}>
      <Group justify="space-between" wrap="nowrap">
        <Text fw={500} size="sm">
          {limit.label}
        </Text>
        <Text fw={600} size="sm">
          {formattedPercent}
        </Text>
      </Group>
      <Progress
        aria-label={t("progressLabel", {
          label: limit.label,
          percent: formattedPercent,
        })}
        color={subscriptionUsageProgressColor(usedPercent)}
        radius="xl"
        size="sm"
        value={usedPercent}
      />
      <Text c="dimmed" size="xs">
        {limit.resets_at
          ? t("resetsAt", { value: formatDateTime(limit.resets_at, format) })
          : t("noReset")}
      </Text>
    </Stack>
  );
}

function ExternalUsage({
  snapshot,
  refreshing,
  onRefresh,
}: {
  snapshot: Extract<SubscriptionUsageSnapshot, { type: "external" }>;
  refreshing: boolean;
  onRefresh: () => Promise<void> | void;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");

  return (
    <UsageSection ariaLabel={t("title")}>
      <Stack gap="sm">
        <UsageHeader refreshing={refreshing} onRefresh={onRefresh} />
        <Text c="dimmed" size="sm">
          {t("externalDescription")}
        </Text>
        <Anchor
          href={snapshot.url}
          rel="noopener noreferrer"
          target="_blank"
          size="sm"
        >
          <Group component="span" gap={rem(6)} wrap="nowrap">
            <span>{t("externalAction")}</span>
            <IconExternalLink aria-label={t("opensNewTab")} size={rem(14)} />
          </Group>
        </Anchor>
        <Freshness fetchedAt={snapshot.fetched_at} />
      </Stack>
    </UsageSection>
  );
}

function UnavailableUsage({
  reason,
  retryable,
  onRefresh,
}: {
  reason: SubscriptionUsageUnavailableReason | null;
  retryable: boolean;
  onRefresh: () => Promise<void> | void;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const reasonKey = reason ?? "request_failed";

  return (
    <UsageSection ariaLabel={t("title")}>
      <Alert
        color="gray"
        icon={<IconAlertTriangle size={rem(16)} />}
        title={t("unavailable")}
        variant="light"
      >
        <Stack gap="sm">
          <Text size="sm">{t(`reasons.${reasonKey}`)}</Text>
          {retryable ? (
            <Button
              onClick={() => void onRefresh()}
              size="compact-sm"
              variant="subtle"
            >
              {t("retry")}
            </Button>
          ) : null}
        </Stack>
      </Alert>
    </UsageSection>
  );
}

function StaleUsage({
  snapshot,
  onRefresh,
}: {
  snapshot: SubscriptionUsageSnapshot;
  onRefresh: () => Promise<void> | void;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");

  return (
    <UsageSection ariaLabel={t("title")}>
      <Stack gap="sm">
        <Alert
          color="yellow"
          icon={<IconAlertTriangle size={rem(16)} />}
          title={t("staleTitle")}
          variant="light"
        >
          <Group justify="space-between" align="center">
            <Text size="sm">{t("staleDescription")}</Text>
            <Button
              onClick={() => void onRefresh()}
              size="compact-sm"
              variant="subtle"
            >
              {t("retry")}
            </Button>
          </Group>
        </Alert>
        {snapshot.type === "available" ? (
          <AvailableUsageContent snapshot={snapshot} />
        ) : (
          <ExternalSnapshotContent snapshot={snapshot} />
        )}
      </Stack>
    </UsageSection>
  );
}

function ExternalSnapshotContent({
  snapshot,
}: {
  snapshot: Extract<SubscriptionUsageSnapshot, { type: "external" }>;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  return (
    <Stack gap="sm">
      <Text c="dimmed" size="sm">
        {t("externalDescription")}
      </Text>
      <Anchor
        href={snapshot.url}
        rel="noopener noreferrer"
        target="_blank"
        size="sm"
      >
        {t("externalAction")}
      </Anchor>
      <Freshness fetchedAt={snapshot.fetched_at} />
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

function FinancialDetails({
  details,
  planLabel,
}: {
  details: NonNullable<SubscriptionUsageAvailableResponse["financial_details"]>;
  planLabel: string | null;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const format = useFormatter();

  if (details.type === "chatgpt") {
    return (
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs" pt="xs">
        {planLabel ? (
          <Detail label={t("financial.plan")} value={planLabel} />
        ) : null}
        {details.has_credits !== null ? (
          <Detail
            label={t("financial.hasCredits")}
            value={t(details.has_credits ? "yes" : "no")}
          />
        ) : null}
        {details.unlimited !== null ? (
          <Detail
            label={t("financial.unlimited")}
            value={t(details.unlimited ? "yes" : "no")}
          />
        ) : null}
        {details.balance !== null ? (
          <Detail label={t("financial.balance")} value={details.balance} />
        ) : null}
        {details.spend_limit !== null ? (
          <Detail
            label={t("financial.spendLimit")}
            value={details.spend_limit}
          />
        ) : null}
        {details.spend_used !== null ? (
          <Detail label={t("financial.spendUsed")} value={details.spend_used} />
        ) : null}
        {details.spend_remaining_percent !== null ? (
          <Detail
            label={t("financial.spendRemaining")}
            value={format.number(details.spend_remaining_percent / 100, {
              maximumFractionDigits: 1,
              style: "percent",
            })}
          />
        ) : null}
        {details.spend_resets_at !== null ? (
          <Detail
            label={t("financial.spendResets")}
            value={formatDateTime(details.spend_resets_at, format)}
          />
        ) : null}
        {details.reached_type !== null ? (
          <Detail
            label={t("financial.reachedType")}
            value={
              details.reached_type === "primary"
                ? t("financial.reachedPrimary")
                : details.reached_type === "secondary"
                  ? t("financial.reachedSecondary")
                  : t("financial.reachedOther")
            }
          />
        ) : null}
      </SimpleGrid>
    );
  }

  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs" pt="xs">
      {planLabel ? (
        <Detail label={t("financial.plan")} value={planLabel} />
      ) : null}
      {details.prepaid_balance_cents !== null ? (
        <Detail
          label={t("financial.prepaidBalance")}
          value={formatUsdCents(details.prepaid_balance_cents, format)}
        />
      ) : null}
      {details.payg_cap_cents !== null ? (
        <Detail
          label={t("financial.paygCap")}
          value={formatUsdCents(details.payg_cap_cents, format)}
        />
      ) : null}
      {details.payg_used_cents !== null ? (
        <Detail
          label={t("financial.paygUsed")}
          value={formatUsdCents(details.payg_used_cents, format)}
        />
      ) : null}
      {details.auto_top_up_enabled !== null ? (
        <Detail
          label={t("financial.autoTopUp")}
          value={t(details.auto_top_up_enabled ? "enabled" : "disabledValue")}
        />
      ) : null}
      {details.auto_top_up_amount_cents !== null ? (
        <Detail
          label={t("financial.autoTopUpAmount")}
          value={formatUsdCents(details.auto_top_up_amount_cents, format)}
        />
      ) : null}
      {details.auto_top_up_monthly_maximum_cents !== null ? (
        <Detail
          label={t("financial.autoTopUpMaximum")}
          value={formatUsdCents(
            details.auto_top_up_monthly_maximum_cents,
            format,
          )}
        />
      ) : null}
    </SimpleGrid>
  );
}

function Detail({
  label,
  value,
}: {
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <Stack gap={rem(2)}>
      <Text c="dimmed" size="xs">
        {label}
      </Text>
      <Text size="sm">{value}</Text>
    </Stack>
  );
}

function DisclosureButton({
  label,
  opened,
  onClick,
}: {
  label: string;
  opened: boolean;
  onClick: () => void;
}): React.ReactElement {
  return (
    <Button
      aria-expanded={opened}
      justify="space-between"
      onClick={onClick}
      rightSection={
        opened ? (
          <IconChevronUp size={rem(14)} />
        ) : (
          <IconChevronDown size={rem(14)} />
        )
      }
      size="compact-sm"
      variant="subtle"
    >
      {label}
    </Button>
  );
}

function UsageSection({
  ariaLabel,
  children,
}: {
  ariaLabel: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <Stack aria-label={ariaLabel} gap="sm" role="region" mt="md">
      <Divider />
      {children}
    </Stack>
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

function formatUsdCents(
  cents: number,
  format: ReturnType<typeof useFormatter>,
): string {
  return format.number(cents / 100, { currency: "USD", style: "currency" });
}
