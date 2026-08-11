"use client";

import {
  Accordion,
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type { RuntimeConfigurationState } from "../types";
import type { RuntimeConfigurationStateResponse } from "@azents/public-client";

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

function stateEvidence(
  configurationState: RuntimeConfigurationStateResponse,
): Array<{
  label:
    | "configurationEvidence.sequence"
    | "configurationEvidence.profile"
    | "configurationEvidence.infrastructure"
    | "configurationEvidence.generation"
    | "configurationEvidence.digest";
  value: string;
}> {
  const profile =
    configurationState.workspace_runtime_profile_id !== null &&
    configurationState.workspace_runtime_profile_version !== null
      ? `${configurationState.workspace_runtime_profile_id} · v${configurationState.workspace_runtime_profile_version}`
      : "—";
  const infrastructure =
    configurationState.infrastructure_profile_id !== null &&
    configurationState.infrastructure_profile_version !== null
      ? `${configurationState.infrastructure_profile_id} · v${configurationState.infrastructure_profile_version}`
      : "—";

  return [
    {
      label: "configurationEvidence.sequence",
      value: configurationState.sequence.toString(),
    },
    {
      label: "configurationEvidence.profile",
      value: profile,
    },
    {
      label: "configurationEvidence.infrastructure",
      value: infrastructure,
    },
    {
      label: "configurationEvidence.generation",
      value: configurationState.target_generation.toString(),
    },
    {
      label: "configurationEvidence.digest",
      value: configurationState.digest ?? "—",
    },
  ];
}

function StatePanel({
  title,
  configurationState,
}: {
  title: string;
  configurationState: RuntimeConfigurationStateResponse;
}): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          {title}
        </Text>
        {stateEvidence(configurationState).map((item) => (
          <Stack key={item.label} gap={0}>
            <Text size="xs" fw={500}>
              {t(item.label)}
            </Text>
            <Text
              size="xs"
              ff="monospace"
              style={{
                overflowWrap: "anywhere",
                wordBreak: "break-word",
              }}
            >
              {item.value}
            </Text>
          </Stack>
        ))}
        {configurationState.reason_code !== null && (
          <Alert color="red" p="xs">
            <Stack gap="xs">
              <Text size="xs">
                {t(
                  `configurationReasons.${configurationReason(
                    configurationState.reason_code,
                  )}`,
                )}
              </Text>
              <Text
                size="xs"
                ff="monospace"
                style={{ overflowWrap: "anywhere" }}
              >
                {configurationState.reason_code}
              </Text>
              {configurationState.missing_capabilities !== null &&
                configurationState.missing_capabilities.length > 0 && (
                  <Text
                    size="xs"
                    ff="monospace"
                    style={{ overflowWrap: "anywhere" }}
                  >
                    {t("configurationMissingCapabilities", {
                      capabilities:
                        configurationState.missing_capabilities.join(", "),
                    })}
                  </Text>
                )}
            </Stack>
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}

export function RuntimeConfigurationStatus({
  state,
}: RuntimeConfigurationStatusProps): React.ReactElement | null {
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
  if (configuration === null) {
    return null;
  }
  const hasTechnicalDetails =
    configuration.desired !== null || configuration.applied !== null;

  return (
    <Paper withBorder p={{ base: "sm", sm: "md" }} radius="md">
      <Stack gap="md">
        <Stack gap="xs">
          <Group justify="space-between" align="center" gap="sm">
            <Text size="sm" fw={700}>
              {t("configurationTitle")}
            </Text>
            <Badge variant="default">
              {t(`configurationStatus.${configuration.status}.label`)}
            </Badge>
          </Group>
          <Text size="sm">
            {t(`configurationStatus.${configuration.status}.description`)}
          </Text>
        </Stack>

        {hasTechnicalDetails && (
          <Accordion variant="contained" radius="md">
            <Accordion.Item value="technical-details">
              <Accordion.Control>
                <Text size="sm" fw={600}>
                  {t("configurationTechnicalDetails")}
                </Text>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="sm">
                  {configuration.status === "applied" &&
                  configuration.applied !== null ? (
                    <StatePanel
                      title={t("configurationCurrent")}
                      configurationState={configuration.applied}
                    />
                  ) : (
                    <>
                      {configuration.desired !== null && (
                        <StatePanel
                          title={t("configurationDesired")}
                          configurationState={configuration.desired}
                        />
                      )}
                      {configuration.applied !== null && (
                        <StatePanel
                          title={t("configurationApplied")}
                          configurationState={configuration.applied}
                        />
                      )}
                    </>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        )}
      </Stack>
    </Paper>
  );
}
