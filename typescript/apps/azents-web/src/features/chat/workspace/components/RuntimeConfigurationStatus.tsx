"use client";

import {
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type { RuntimeConfigurationState } from "../types";
import type { RuntimeConfigurationRevisionResponse } from "@azents/public-client";

interface RuntimeConfigurationStatusProps {
  state: RuntimeConfigurationState;
}

type ConfigurationReason =
  | "sourceMismatch"
  | "profileDisabled"
  | "providerUnavailable"
  | "capabilityUnavailable"
  | "profileInvalid"
  | "unknown";

function configurationReason(reasonCode: string | null): ConfigurationReason {
  switch (reasonCode) {
    case "workspace_profile_provider_mismatch":
    case "infrastructure_profile_provider_mismatch":
    case "workspace_profile_infrastructure_mismatch":
      return "sourceMismatch";
    case "workspace_profile_disabled":
    case "infrastructure_profile_disabled":
      return "profileDisabled";
    case "provider_scope_unsupported":
    case "provider_not_active":
    case "provider_disabled":
    case "provider_workspace_unavailable":
    case "provider_disconnected":
      return "providerUnavailable";
    case "provider_capability_unavailable":
    case "provider_capability_invalid":
    case "profile_incompatible":
      return "capabilityUnavailable";
    case "profile_document_invalid":
      return "profileInvalid";
    default:
      return "unknown";
  }
}

function revisionEvidence(
  revision: RuntimeConfigurationRevisionResponse,
): Array<{
  label:
    | "configurationEvidence.revision"
    | "configurationEvidence.profile"
    | "configurationEvidence.infrastructure"
    | "configurationEvidence.generation"
    | "configurationEvidence.digest";
  value: string;
}> {
  return [
    { label: "configurationEvidence.revision", value: revision.id },
    {
      label: "configurationEvidence.profile",
      value: `${revision.workspace_runtime_profile_id} · v${revision.workspace_runtime_profile_version}`,
    },
    {
      label: "configurationEvidence.infrastructure",
      value: `${revision.infrastructure_profile_id} · v${revision.infrastructure_profile_version}`,
    },
    {
      label: "configurationEvidence.generation",
      value: revision.target_desired_generation.toString(),
    },
    { label: "configurationEvidence.digest", value: revision.digest },
  ];
}

function RevisionPanel({
  title,
  revision,
  empty,
}: {
  title: string;
  revision: RuntimeConfigurationRevisionResponse | null;
  empty: string;
}): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          {title}
        </Text>
        {revision === null ? (
          <Text size="sm" c="dimmed">
            {empty}
          </Text>
        ) : (
          <>
            {revisionEvidence(revision).map((item) => (
              <Group
                key={item.label}
                justify="space-between"
                align="flex-start"
                gap="sm"
                wrap="nowrap"
              >
                <Text size="xs" c="dimmed">
                  {t(item.label)}
                </Text>
                <Text
                  size="xs"
                  ff="monospace"
                  ta="right"
                  style={{ overflowWrap: "anywhere" }}
                >
                  {item.value}
                </Text>
              </Group>
            ))}
            {revision.reason_code !== null && (
              <Alert color="red" p="xs">
                <Stack gap={2}>
                  <Text size="xs">
                    {t(
                      `configurationReasons.${configurationReason(
                        revision.reason_code,
                      )}`,
                    )}
                  </Text>
                  <Text size="xs" c="dimmed" ff="monospace">
                    {revision.reason_code}
                  </Text>
                  {revision.missing_capabilities.length > 0 && (
                    <Text size="xs" c="dimmed" ff="monospace">
                      {t("configurationMissingCapabilities", {
                        capabilities: revision.missing_capabilities.join(", "),
                      })}
                    </Text>
                  )}
                </Stack>
              </Alert>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );
}

export function RuntimeConfigurationStatus({
  state,
}: RuntimeConfigurationStatusProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  if (state.type === "LOADING") {
    return (
      <Paper withBorder p="md" radius="md">
        <Group gap="sm">
          <Loader size="xs" />
          <Text size="sm">{t("configurationLoading")}</Text>
        </Group>
      </Paper>
    );
  }

  if (state.type === "ERROR") {
    return <Alert color="red">{state.message}</Alert>;
  }

  const { configuration } = state;
  const statusColor =
    configuration.status === "applied"
      ? "green"
      : configuration.status === "waiting_for_recreation"
        ? "yellow"
        : configuration.status === "configured_not_created"
          ? "blue"
          : "red";

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <Stack gap="xs">
            <Text size="sm" fw={700}>
              {t("configurationTitle")}
            </Text>
            <Text size="xs" c="dimmed">
              {t(`configurationStatus.${configuration.status}.description`)}
            </Text>
          </Stack>
          <Badge color={statusColor} variant="light">
            {t(`configurationStatus.${configuration.status}.label`)}
          </Badge>
        </Group>

        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <RevisionPanel
            title={t("configurationDesired")}
            revision={configuration.desired}
            empty={t("configurationNoDesired")}
          />
          <RevisionPanel
            title={t("configurationApplied")}
            revision={configuration.applied}
            empty={t("configurationNoApplied")}
          />
        </SimpleGrid>
      </Stack>
    </Paper>
  );
}
