"use client";

import {
  Alert,
  Badge,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type {
  AgentRuntimeLifecyclePresentationResponse,
  RuntimeConfigurationStatus,
} from "@azents/public-client";

interface RuntimeLifecycleStatusProps {
  lifecycle: AgentRuntimeLifecyclePresentationResponse;
  configurationStatus?: RuntimeConfigurationStatus | null;
  compact?: boolean;
}

type LifecycleFieldKey =
  | "target"
  | "convergence"
  | "providerResource"
  | "providerConnection"
  | "runner"
  | "configuration";

function availabilityColor(
  availability: AgentRuntimeLifecyclePresentationResponse["availability"],
): string {
  switch (availability) {
    case "ready":
      return "green";
    case "stopped":
      return "gray";
    case "transitioning":
      return "blue";
    case "provider_disconnected":
    case "runner_unavailable":
    case "configuration_blocked":
    case "removing":
      return "yellow";
    case "failed":
      return "red";
  }
}

export function RuntimeLifecycleStatus({
  lifecycle,
  configurationStatus,
  compact = false,
}: RuntimeLifecycleStatusProps): React.ReactElement {
  const t = useTranslations("runtimeLifecycle");
  const reason = (() => {
    switch (lifecycle.reason_code) {
      case null:
        return null;
      case "runtime_removal_in_progress":
        return t("reasons.runtimeRemovalInProgress");
      case "runtime_failed":
        return t("reasons.runtimeFailed");
      case "provider_failed":
        return t("reasons.providerFailed");
      case "runtime_recreation_required":
        return t("reasons.runtimeRecreationRequired");
      case "provider_disabled":
        return t("reasons.providerDisabled");
      case "provider_workspace_unavailable":
        return t("reasons.providerWorkspaceUnavailable");
      case "provider_disconnected":
        return t("reasons.providerDisconnected");
      case "provider_capability_unavailable":
        return t("reasons.providerCapabilityUnavailable");
      case "provider_capability_invalid":
        return t("reasons.providerCapabilityInvalid");
      case "profile_document_invalid":
        return t("reasons.profileDocumentInvalid");
      case "profile_incompatible":
        return t("reasons.profileIncompatible");
      case "runtime_configuration_blocked":
        return t("reasons.runtimeConfigurationBlocked");
      case "runtime_profile_required":
        return t("reasons.runtimeProfileRequired");
      case "runtime_resetting":
        return t("reasons.runtimeResetting");
      case "runtime_recovering":
        return t("reasons.runtimeRecovering");
      case "runtime_starting":
        return t("reasons.runtimeStarting");
      case "runtime_stopping":
        return t("reasons.runtimeStopping");
      case "runner_unknown":
        return t("reasons.runnerUnknown");
      case "runner_disconnected":
        return t("reasons.runnerDisconnected");
      case "runner_starting":
        return t("reasons.runnerStarting");
      case "runner_degraded":
        return t("reasons.runnerDegraded");
      case "runner_failed":
        return t("reasons.runnerFailed");
      default:
        return t("reasons.unknown");
    }
  })();
  const facts: (readonly [LifecycleFieldKey, string])[] = [
    ["target", t(`target.${lifecycle.target}`)],
    ["convergence", t(`convergence.${lifecycle.convergence}`)],
    ["providerResource", t(`providerResource.${lifecycle.provider.resource}`)],
    [
      "providerConnection",
      t(`providerConnection.${lifecycle.provider.connection}`),
    ],
    ["runner", t(`runner.${lifecycle.runner.state}`)],
  ];
  if (configurationStatus) {
    facts.push(["configuration", t(`configuration.${configurationStatus}`)]);
  }

  return (
    <Paper withBorder radius="lg" p={compact ? "md" : "lg"}>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <Stack gap={2}>
            <Text fw={700}>{t("title")}</Text>
            {!compact ? (
              <Text c="dimmed" size="sm">
                {t("description")}
              </Text>
            ) : null}
          </Stack>
          <Badge
            color={availabilityColor(lifecycle.availability)}
            variant="light"
          >
            {t(`availability.${lifecycle.availability}`)}
          </Badge>
        </Group>
        <SimpleGrid cols={{ base: 2, sm: compact ? 3 : 6 }} spacing="sm">
          {facts.map(([key, value]) => (
            <Stack key={key} gap={2}>
              <Text c="dimmed" size="xs">
                {t(`fields.${key}`)}
              </Text>
              <Text fw={600} size="sm">
                {value}
              </Text>
            </Stack>
          ))}
        </SimpleGrid>
        {reason ? (
          <Alert color={availabilityColor(lifecycle.availability)}>
            {reason}
          </Alert>
        ) : null}
        {!compact ? (
          <Text c="dimmed" size="xs">
            {t("generation", { generation: lifecycle.desired_generation })}
          </Text>
        ) : null}
      </Stack>
    </Paper>
  );
}
