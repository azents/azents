"use client";

import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import {
  canApplyRuntimeExecution,
  runtimePolicyReasonMessageKey,
} from "../runtimeExecutionPresentation";
import type { AgentRuntimeStatusState } from "../types";
import type {
  RuntimeExecutionConfiguredSummaryResponse,
  RuntimeExecutionPolicyStatus,
  RuntimeExecutionSnapshotSummaryResponse,
} from "@azents/public-client";

interface AgentRuntimePolicyStatusProps {
  state: AgentRuntimeStatusState;
  applying: boolean;
  onApply: () => void;
}

function statusColor(status: RuntimeExecutionPolicyStatus): string {
  switch (status) {
    case "configured":
      return "blue";
    case "pending":
      return "yellow";
    case "applied":
      return "green";
    case "unavailable":
      return "orange";
    case "divergent":
      return "red";
  }
}

function formatBytes(bytes: number): string {
  for (const [unit, divisor] of [
    ["GiB", 1_073_741_824],
    ["MiB", 1_048_576],
    ["KiB", 1_024],
  ] as const) {
    if (bytes % divisor === 0) {
      return `${bytes / divisor} ${unit}`;
    }
  }
  return `${bytes} B`;
}

function Summary({
  title,
  summary,
}: {
  title: string;
  summary:
    | RuntimeExecutionConfiguredSummaryResponse
    | RuntimeExecutionSnapshotSummaryResponse
    | null;
}): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.agentPage");
  if (summary === null) {
    return (
      <Paper withBorder p="md" radius="md">
        <Stack gap={3}>
          <Text size="sm" fw={600}>
            {title}
          </Text>
          <Text size="sm" c="dimmed">
            {t("none")}
          </Text>
        </Stack>
      </Paper>
    );
  }
  const storageLabel = {
    none: t("storageModes.none"),
    ephemeral: t("storageModes.ephemeral"),
    persistent: t("storageModes.persistent"),
  }[summary.storage_mode];
  const networkLabel = {
    none: t("networkModes.none"),
    restricted: t("networkModes.restricted"),
    direct: t("networkModes.direct"),
  }[summary.network_mode];
  const capabilityLabels: Record<string, string> = {
    "container.image_build": t("capabilityLabels.imageBuild"),
    "container.run": t("capabilityLabels.containerRun"),
    "container.compose": t("capabilityLabels.compose"),
  };
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={600}>
            {title}
          </Text>
          {"desired_generation" in summary && (
            <Badge variant="light">
              {t("generation", {
                generation: summary.desired_generation,
              })}
            </Badge>
          )}
        </Group>
        <Text size="sm">
          {t("profileValue", { profile: summary.profile_id })}
        </Text>
        <Text size="xs" c="dimmed">
          {t("policyFingerprint")}: <Code>{summary.digest.slice(0, 16)}</Code>
        </Text>
        <Text size="xs" c="dimmed">
          {t("storage")}: {storageLabel}
          {summary.storage_capacity_bytes === null
            ? ""
            : ` · ${formatBytes(summary.storage_capacity_bytes)}`}
        </Text>
        <Text size="xs" c="dimmed">
          {t("network")}: {networkLabel}
        </Text>
        <Group gap="xs">
          {summary.capabilities.map((capability) => (
            <Badge
              key={capability.module_id}
              color={capability.enabled ? "blue" : "gray"}
              variant="light"
              size="sm"
            >
              {capabilityLabels[capability.module_id] ?? capability.module_id}:{" "}
              {capability.enabled ? t("enabled") : t("disabled")}
            </Badge>
          ))}
        </Group>
      </Stack>
    </Paper>
  );
}

export function AgentRuntimePolicyStatus({
  state,
  applying,
  onApply,
}: AgentRuntimePolicyStatusProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.agentPage");
  if (state.type === "LOADING") {
    return (
      <Paper withBorder p="md" radius="md">
        <Group>
          <Loader size="sm" />
          <Text>{t("statusLoading")}</Text>
        </Group>
      </Paper>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="yellow" title={t("statusError")}>
        {state.message}
      </Alert>
    );
  }
  const { status } = state;
  const statusLabel = {
    configured: t("status.configured"),
    pending: t("status.pending"),
    applied: t("status.applied"),
    unavailable: t("status.unavailable"),
    divergent: t("status.divergent"),
  }[status.status];
  const statusHelp = {
    configured: t("statusHelp.configured"),
    pending: t("statusHelp.pending"),
    applied: t("statusHelp.applied"),
    unavailable: t("statusHelp.unavailable"),
    divergent: t("statusHelp.divergent"),
  }[status.status];
  const actionLabel = {
    none: t("actions.none"),
    apply: t("actions.apply"),
    wait: t("actions.wait"),
    administrator_action: t("actions.administrator_action"),
  }[status.required_action];
  const reasonMessages = status.reason_codes.map((reason) => {
    const key = runtimePolicyReasonMessageKey(reason);
    if (key === "reasonExplanations.runtime_failure") {
      return t(key, { code: reason });
    }
    return t(key);
  });
  const fieldLabels: Record<string, string> = {
    "image_build.enabled": t("fieldLabels.imageBuild"),
    "container_run.enabled": t("fieldLabels.containerRun"),
    "compose.enabled": t("fieldLabels.compose"),
    "resources.cpu_request_millicores": t("fieldLabels.cpuRequest"),
    "resources.cpu_limit_millicores": t("fieldLabels.cpuLimit"),
    "resources.memory_request_bytes": t("fieldLabels.memoryRequest"),
    "resources.memory_limit_bytes": t("fieldLabels.memoryLimit"),
    "resources.pids": t("fieldLabels.pidLimit"),
    "resources.container_count": t("fieldLabels.containerCount"),
    "resources.ephemeral_storage_bytes": t("fieldLabels.ephemeralStorage"),
    "resources.persistent_storage_bytes": t("fieldLabels.persistentStorage"),
    "engine_storage.mode": t("fieldLabels.dockerStoragePolicy"),
    "engine_storage.capacity_bytes": t("fieldLabels.dockerStorageCapacity"),
    "network_egress.mode": t("fieldLabels.networkPolicy"),
    "network_egress.allowed_destinations": t("fieldLabels.allowedIpRanges"),
    "network_egress.denied_destinations": t("fieldLabels.blockedIpRanges"),
  };
  const fieldsByLayer = Object.entries(status.governing_layers).reduce<
    Record<string, string[]>
  >((groups, [path, layer]) => {
    const group = groups[layer] ?? [];
    group.push(fieldLabels[path] ?? path);
    groups[layer] = group;
    return groups;
  }, {});

  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Group gap="xs">
              <Text fw={600}>{t("statusTitle")}</Text>
              <Badge color={statusColor(status.status)} variant="light">
                {statusLabel}
              </Badge>
            </Group>
            <Text size="sm" c="dimmed">
              {statusHelp}
            </Text>
            <Text size="sm">{actionLabel}</Text>
          </Stack>
          {canApplyRuntimeExecution(status.required_action) && (
            <Button loading={applying} onClick={onApply}>
              {applying ? t("applying") : t("apply")}
            </Button>
          )}
        </Group>
        {(status.reason_codes.length > 0 ||
          Object.keys(status.governing_layers).length > 0) && (
          <Stack gap="md" mt="md">
            {reasonMessages.length > 0 && (
              <Stack gap={3}>
                <Text size="xs" fw={600} c="dimmed">
                  {t("whyUnavailable")}
                </Text>
                {reasonMessages.map((message, index) => (
                  <Text
                    key={`${status.reason_codes[index]}-${index}`}
                    size="sm"
                  >
                    {message}
                  </Text>
                ))}
              </Stack>
            )}
            {Object.keys(fieldsByLayer).length > 0 && (
              <Stack gap={3}>
                <Text size="xs" fw={600} c="dimmed">
                  {t("governingLayers")}
                </Text>
                {Object.entries(fieldsByLayer).map(([layer, fields]) => (
                  <Text key={layer} size="sm">
                    <Text component="span" fw={600}>
                      {{
                        profile: t("layerLabels.profile"),
                        workspace: t("layerLabels.workspace"),
                        agent: t("layerLabels.agent"),
                      }[layer] ?? layer}
                      :{" "}
                    </Text>
                    {fields.join(", ")}
                  </Text>
                ))}
              </Stack>
            )}
          </Stack>
        )}
      </Paper>
      <Text fw={600}>{t("comparisonTitle")}</Text>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Summary title={t("configured")} summary={status.configured} />
        <Summary title={t("target")} summary={status.target} />
        <Summary title={t("applied")} summary={status.applied} />
      </SimpleGrid>
    </Stack>
  );
}
