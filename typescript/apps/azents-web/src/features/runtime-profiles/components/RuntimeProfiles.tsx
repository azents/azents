"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Paper,
  Progress,
  rem,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconPlus, IconRefresh, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { runtimeProfileAvailabilityReason } from "../runtimeProfilePresentation";
import { RuntimeProfileDeleteModal } from "./RuntimeProfileDeleteModal";
import { RuntimeProfileFormModal } from "./RuntimeProfileFormModal";
import type { RuntimeProfilesContainerOutput } from "../containers/useRuntimeProfilesContainer";
import type {
  RuntimeNetworkProjection,
  SelectableInfrastructureProfileResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";

function infrastructureLabel(
  profile: WorkspaceRuntimeProfileResponse,
  infrastructureProfiles: SelectableInfrastructureProfileResponse[],
): string {
  const infrastructureProfile = infrastructureProfiles.find(
    (item) => item.id === profile.infrastructure_profile_id,
  );
  if (!infrastructureProfile) {
    return profile.infrastructure_profile_id;
  }
  return `${infrastructureProfile.provider_display_name} · ${infrastructureProfile.display_name}`;
}

function NetworkProjectionSummary({
  network,
}: {
  network: RuntimeNetworkProjection;
}): React.ReactElement {
  const t = useTranslations("workspace.runtimeProfiles");
  const details = [
    network.allowed_cidrs.length > 0
      ? t("networkAllowedCidrs", {
          values: network.allowed_cidrs.join(", "),
        })
      : null,
    network.denied_cidrs.length > 0
      ? t("networkDeniedCidrs", {
          values: network.denied_cidrs.join(", "),
        })
      : null,
    network.domain_mode !== null
      ? t("networkDomainMode", {
          mode: t(`proxyDomainMode.${network.domain_mode}`),
        })
      : null,
    network.allowed_domains.length > 0
      ? t("networkAllowedDomains", {
          values: network.allowed_domains.join(", "),
        })
      : null,
    network.denied_domains.length > 0
      ? t("networkDeniedDomains", {
          values: network.denied_domains.join(", "),
        })
      : null,
  ].filter((item) => item !== null);

  return (
    <Stack gap={2}>
      <Badge variant="light">{t(`networkMode.${network.mode}`)}</Badge>
      {details.map((detail) => (
        <Text key={detail} size="xs" c="dimmed">
          {detail}
        </Text>
      ))}
    </Stack>
  );
}

export function RuntimeProfiles(
  props: RuntimeProfilesContainerOutput,
): React.ReactElement {
  const {
    state,
    editorState,
    mutationState,
    operationState,
    deletionState,
    deletionFeedbackState,
    canManage,
    canDelete,
    onOpenCreate,
    onOpenEdit,
    onCloseEditor,
    onSubmit,
    onSetDefault,
    onRecreate,
    onOpenDelete,
    onCloseDelete,
    onConfirmDelete,
    onDismissDeletionFeedback,
  } = props;
  const t = useTranslations("workspace.runtimeProfiles");

  if (state.type === "LOADING") {
    return (
      <Box style={{ height: "100%", overflow: "auto", minHeight: 0 }}>
        <Group justify="center" p="xl">
          <Loader />
        </Group>
      </Box>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Box style={{ height: "100%", overflow: "auto", minHeight: 0 }} p="md">
        <Alert color="red">{state.message}</Alert>
      </Box>
    );
  }

  const defaultOptions = state.profiles.map((profile) => ({
    value: profile.id,
    label:
      profile.available && profile.lifecycle === "active"
        ? profile.display_name
        : `${profile.display_name} · ${t("unavailable")}`,
    disabled: !profile.available || profile.lifecycle === "disabled",
  }));

  return (
    <Box style={{ height: "100%", overflow: "auto", minHeight: 0 }}>
      <Stack gap="lg" p="md" maw={rem(1080)} mx="auto" w="100%">
        <Group justify="space-between" align="flex-start">
          <Stack gap="xs">
            <Title order={3}>{t("headline")}</Title>
            <Text size="sm" c="dimmed">
              {t("description")}
            </Text>
          </Stack>
          {canManage && (
            <Button
              leftSection={<IconPlus size={rem(16)} />}
              onClick={onOpenCreate}
              disabled={state.infrastructureProfiles.length === 0}
            >
              {t("addProfile")}
            </Button>
          )}
        </Group>

        {state.infrastructureProfiles.length === 0 && (
          <Alert color="yellow" title={t("noInfrastructureTitle")}>
            {t("noInfrastructureDescription")}
          </Alert>
        )}

        {deletionFeedbackState.type === "SUCCESS" && (
          <Alert
            color="green"
            title={t("deleteSuccessTitle", {
              name: deletionFeedbackState.profileName,
            })}
            withCloseButton
            onClose={onDismissDeletionFeedback}
          >
            <Stack gap={2}>
              <Text size="sm">
                {deletionFeedbackState.result.cleared_workspace_default
                  ? t("deleteSuccessDefaultCleared")
                  : t("deleteSuccessDefaultUnchanged")}
              </Text>
              <Text size="sm">
                {t("deleteSuccessAgents", {
                  count: deletionFeedbackState.result.cleared_agent_count,
                })}
              </Text>
              <Text size="sm">
                {t("deleteSuccessRunningRuntimes", {
                  count:
                    deletionFeedbackState.result.affected_running_runtime_count,
                })}
              </Text>
              <Text size="sm">
                {t("deleteSuccessRecreationOperations", {
                  count:
                    deletionFeedbackState.result
                      .superseded_recreation_operation_count,
                })}
              </Text>
            </Stack>
          </Alert>
        )}

        <Paper withBorder p="md">
          <Stack gap="xs">
            <Text fw={600}>{t("defaultTitle")}</Text>
            <Text size="sm" c="dimmed">
              {t("defaultDescription")}
            </Text>
            <Select
              data={defaultOptions}
              value={state.defaultProfile.runtime_profile_id}
              onChange={onSetDefault}
              clearable
              disabled={!canManage || mutationState.type === "SUBMITTING"}
              placeholder={t("defaultPlaceholder")}
            />
          </Stack>
        </Paper>

        {state.profiles.length === 0 ? (
          <Alert color="blue" title={t("emptyTitle")}>
            {t("emptyDescription")}
          </Alert>
        ) : (
          <Paper withBorder>
            <ScrollArea>
              <Table
                verticalSpacing="sm"
                horizontalSpacing="md"
                style={{ minWidth: rem(720) }}
              >
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t("nameColumn")}</Table.Th>
                    <Table.Th>{t("infrastructureColumn")}</Table.Th>
                    <Table.Th>{t("networkColumn")}</Table.Th>
                    <Table.Th>{t("statusColumn")}</Table.Th>
                    <Table.Th>{t("versionColumn")}</Table.Th>
                    <Table.Th>{t("actionsColumn")}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {state.profiles.map((profile) => (
                    <Table.Tr key={profile.id}>
                      <Table.Td>
                        <Stack gap={2}>
                          <Group gap="xs">
                            <Text fw={600}>{profile.display_name}</Text>
                            {state.defaultProfile.runtime_profile_id ===
                              profile.id && (
                              <Badge size="sm" variant="light">
                                {t("defaultBadge")}
                              </Badge>
                            )}
                          </Group>
                          <Text size="xs" c="dimmed">
                            {profile.description || t("noDescription")}
                          </Text>
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">
                          {infrastructureLabel(
                            profile,
                            state.infrastructureProfiles,
                          )}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {profile.effective_network === null ? (
                          <Text size="xs" c="dimmed">
                            {t("networkUnavailable")}
                          </Text>
                        ) : (
                          <NetworkProjectionSummary
                            network={profile.effective_network}
                          />
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Group gap="xs" wrap="wrap">
                          <Badge
                            color={
                              profile.available && profile.compatible
                                ? "green"
                                : "red"
                            }
                            variant="light"
                          >
                            {profile.available
                              ? t("available")
                              : t("unavailable")}
                          </Badge>
                          {profile.lifecycle === "disabled" && (
                            <Badge color="gray" variant="outline">
                              {t("disabled")}
                            </Badge>
                          )}
                        </Group>
                        {!profile.available && (
                          <Stack gap={2} mt="xs">
                            <Text size="xs" c="red">
                              {t(
                                `availabilityReasons.${runtimeProfileAvailabilityReason(profile.availability_reason_code)}`,
                              )}
                            </Text>
                            {profile.availability_reason_code !== null && (
                              <Text size="xs" c="dimmed" ff="monospace">
                                {profile.availability_reason_code}
                              </Text>
                            )}
                            {profile.missing_capabilities.length > 0 && (
                              <Text size="xs" c="dimmed" ff="monospace">
                                {t("missingCapabilities", {
                                  capabilities:
                                    profile.missing_capabilities.join(", "),
                                })}
                              </Text>
                            )}
                          </Stack>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">v{profile.version}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap="xs" wrap="nowrap">
                          <Button
                            size="xs"
                            variant="subtle"
                            onClick={() => onOpenEdit(profile)}
                            disabled={!canManage}
                          >
                            {t("edit")}
                          </Button>
                          <Button
                            size="xs"
                            variant="light"
                            leftSection={<IconRefresh size={rem(14)} />}
                            onClick={() => onRecreate(profile)}
                            disabled={
                              !canManage ||
                              !profile.available ||
                              mutationState.type === "SUBMITTING"
                            }
                          >
                            {t("recreate")}
                          </Button>
                          {canDelete && (
                            <Button
                              aria-label={t("deleteActionLabel", {
                                name: profile.display_name,
                              })}
                              color="red"
                              leftSection={<IconTrash size={rem(14)} />}
                              size="xs"
                              variant="subtle"
                              onClick={() => onOpenDelete(profile)}
                              disabled={
                                mutationState.type === "SUBMITTING" ||
                                deletionState.type === "SUBMITTING"
                              }
                            >
                              {t("delete")}
                            </Button>
                          )}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </Paper>
        )}

        {operationState.type === "LOADING" && (
          <Paper withBorder p="md">
            <Group gap="sm">
              <Loader size="sm" />
              <Text size="sm">{t("operationLoading")}</Text>
            </Group>
          </Paper>
        )}
        {operationState.type === "ERROR" && (
          <Alert color="red">{operationState.message}</Alert>
        )}
        {operationState.type === "LOADED" && (
          <Paper withBorder p="md">
            <Stack gap="sm">
              <Group justify="space-between">
                <Text fw={600}>{t("operationTitle")}</Text>
                <Badge
                  color={
                    operationState.operation.status === "completed"
                      ? "green"
                      : operationState.operation.status ===
                            "completed_with_failures" ||
                          operationState.operation.status === "failed"
                        ? "red"
                        : "blue"
                  }
                >
                  {t(`operationStatus.${operationState.operation.status}`)}
                </Badge>
              </Group>
              <Progress
                value={
                  operationState.operation.total_count === 0
                    ? 100
                    : ((operationState.operation.succeeded_count +
                        operationState.operation.skipped_count +
                        operationState.operation.failed_count) /
                        operationState.operation.total_count) *
                      100
                }
              />
              <Text size="sm" c="dimmed">
                {t("operationCounts", {
                  total: operationState.operation.total_count,
                  succeeded: operationState.operation.succeeded_count,
                  running: operationState.operation.running_count,
                  failed: operationState.operation.failed_count,
                  skipped: operationState.operation.skipped_count,
                })}
              </Text>
              <ScrollArea mah={rem(240)}>
                <Stack gap="xs">
                  {operationState.operation.items.map((item) => (
                    <Alert
                      key={item.runtime_id}
                      color={item.status === "failed" ? "red" : "yellow"}
                      title={`${item.runtime_id} · ${t(
                        `operationItemStatus.${item.status}`,
                      )}`}
                    >
                      <Stack gap={2}>
                        <Text size="sm">
                          {item.failure_message ?? t("operationItemNoDetail")}
                        </Text>
                        {item.failure_code !== null && (
                          <Text size="xs" c="dimmed" ff="monospace">
                            {item.failure_code}
                          </Text>
                        )}
                      </Stack>
                    </Alert>
                  ))}
                </Stack>
              </ScrollArea>
            </Stack>
          </Paper>
        )}

        {mutationState.type === "IDLE" &&
          mutationState.error !== null &&
          editorState.type === "CLOSED" && (
            <Alert color="red">{mutationState.error}</Alert>
          )}
      </Stack>

      <RuntimeProfileFormModal
        editorState={editorState}
        mutationState={mutationState}
        infrastructureProfiles={state.infrastructureProfiles}
        onClose={onCloseEditor}
        onSubmit={onSubmit}
      />
      <RuntimeProfileDeleteModal
        state={deletionState}
        onClose={onCloseDelete}
        onConfirm={onConfirmDelete}
      />
    </Box>
  );
}
