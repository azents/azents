"use client";

/**
 * LLM Settings UI component.
 *
 * Displays LLM Provider Integration list and provides create/update/delete UI plus workspace default model settings.
 * Only Owner can manage; Manager/Member are read-only.
 */

import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Container,
  Group,
  Loader,
  rem,
  Stack,
  Switch,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconEdit, IconPlus, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { IntegrationFormModal } from "./IntegrationFormModal";
import { WorkspaceModelSettingsCard } from "./WorkspaceModelSettingsCard";
import type { LlmSettingsContainerOutput } from "../containers/useLlmSettingsContainer";
import type { LlmProviderIntegrationResponse } from "@azents/public-client";
import type { ReactNode } from "react";

type ProviderLabels = Record<
  | "openai"
  | "anthropic"
  | "google_gemini"
  | "aws_bedrock"
  | "google_vertex_ai"
  | "chatgpt_oauth"
  | "xai"
  | "xai_oauth"
  | "openrouter",
  string
>;

function providerColor(provider: string): string {
  switch (provider) {
    case "openai":
      return "green";
    case "anthropic":
      return "orange";
    case "google_gemini":
    case "google_vertex_ai":
      return "blue";
    case "aws_bedrock":
      return "yellow";
    case "chatgpt_oauth":
      return "teal";
    case "xai":
    case "xai_oauth":
      return "dark";
    case "openrouter":
      return "violet";
    default:
      return "gray";
  }
}

function labelForProvider(provider: string, labels: ProviderLabels): string {
  switch (provider) {
    case "openai":
      return labels.openai;
    case "anthropic":
      return labels.anthropic;
    case "google_gemini":
      return labels.google_gemini;
    case "aws_bedrock":
      return labels.aws_bedrock;
    case "google_vertex_ai":
      return labels.google_vertex_ai;
    case "chatgpt_oauth":
      return labels.chatgpt_oauth;
    case "xai":
      return labels.xai;
    case "xai_oauth":
      return labels.xai_oauth;
    case "openrouter":
      return labels.openrouter;
    default:
      return provider;
  }
}

export interface LlmSettingsProps extends LlmSettingsContainerOutput {
  renderSubscriptionUsage: (
    integration: LlmProviderIntegrationResponse,
  ) => ReactNode;
}

export function LlmSettings(props: LlmSettingsProps): React.ReactElement {
  const {
    listState,
    formModal,
    mutationState,
    canManage,
    providerOptions,
    availableProviderValues,
    modelOptions,
    catalogStates,
    modelsLoading,
    renderSubscriptionUsage,
    onOpenCreate,
    onOpenEdit,
    onCloseModal,
    onCreate,
    onUpdate,
    onDelete,
    onToggleEnabled,
    onSyncCatalog,
    onUpdateWorkspaceModelSettings,
  } = props;
  const t = useTranslations("workspace.llmSettings");

  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={3}>{t("headline")}</Title>
          {canManage && (
            <Button
              leftSection={<IconPlus size={rem(16)} />}
              onClick={onOpenCreate}
            >
              {t("addIntegration")}
            </Button>
          )}
        </Group>

        <Text c="dimmed" size="sm">
          {t("description")}
        </Text>

        {listState.type === "LOADING" && <Loader />}
        {listState.type === "ERROR" && (
          <Alert color="red">{t("loadError")}</Alert>
        )}
        {listState.type === "READY" && (
          <WorkspaceModelSettingsCard
            settings={listState.workspaceModelSettings}
            handle={props.handle}
            providerOptions={providerOptions}
            modelOptions={modelOptions}
            catalogStates={catalogStates}
            modelsLoading={modelsLoading}
            canManage={canManage}
            submitting={mutationState.type === "SUBMITTING"}
            error={mutationState.type === "IDLE" ? mutationState.error : null}
            onSyncCatalog={onSyncCatalog}
            onSubmit={onUpdateWorkspaceModelSettings}
          />
        )}
        {listState.type === "READY" && listState.integrations.length === 0 && (
          <Text c="dimmed">{t("empty")}</Text>
        )}
        {listState.type === "READY" &&
          listState.integrations.map((integration) => (
            <IntegrationCard
              key={integration.id}
              integration={integration}
              canManage={canManage}
              onEdit={onOpenEdit}
              onDelete={onDelete}
              onToggleEnabled={onToggleEnabled}
              usage={renderSubscriptionUsage(integration)}
            />
          ))}

        <IntegrationFormModal
          handle={props.handle}
          availableProviderValues={availableProviderValues}
          formModal={formModal}
          mutationState={mutationState}
          onClose={onCloseModal}
          onCreate={onCreate}
          onUpdate={onUpdate}
        />
      </Stack>
    </Container>
  );
}

/** Integration card */
function IntegrationCard({
  integration,
  canManage,
  onEdit,
  onDelete,
  onToggleEnabled,
  usage,
}: {
  integration: LlmProviderIntegrationResponse;
  canManage: boolean;
  onEdit: (integration: LlmProviderIntegrationResponse) => void;
  onDelete: (id: string) => void;
  onToggleEnabled: (
    integration: LlmProviderIntegrationResponse,
    enabled: boolean,
  ) => void;
  usage: ReactNode;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");
  const providerLabels: ProviderLabels = {
    openai: t("providers.openai"),
    anthropic: t("providers.anthropic"),
    google_gemini: t("providers.google_gemini"),
    aws_bedrock: t("providers.aws_bedrock"),
    google_vertex_ai: t("providers.google_vertex_ai"),
    chatgpt_oauth: t("providers.chatgpt_oauth"),
    xai: t("providers.xai"),
    xai_oauth: t("providers.xai_oauth"),
    openrouter: t("providers.openrouter"),
  };

  return (
    <Card withBorder padding="md">
      <Stack gap={0}>
        <Group justify="space-between" align="flex-start">
          <Group gap="sm">
            <Badge color={providerColor(integration.provider)} variant="light">
              {labelForProvider(integration.provider, providerLabels)}
            </Badge>
            <Text fw={500}>{integration.name}</Text>
            {!integration.enabled && (
              <Badge color="gray" variant="outline" size="sm">
                {t("disabled")}
              </Badge>
            )}
          </Group>
          {canManage && (
            <Group gap="xs" wrap="nowrap">
              <Switch
                aria-label={t("toggleIntegration", {
                  name: integration.name,
                })}
                checked={integration.enabled}
                onChange={(e) =>
                  onToggleEnabled(integration, e.currentTarget.checked)
                }
                size="sm"
              />
              <Tooltip label={t("editIntegration", { name: integration.name })}>
                <ActionIcon
                  aria-label={t("editIntegration", { name: integration.name })}
                  variant="subtle"
                  onClick={() => onEdit(integration)}
                >
                  <IconEdit size={rem(16)} />
                </ActionIcon>
              </Tooltip>
              <Tooltip
                label={t("deleteIntegration", { name: integration.name })}
              >
                <ActionIcon
                  aria-label={t("deleteIntegration", {
                    name: integration.name,
                  })}
                  variant="subtle"
                  color="red"
                  onClick={() => onDelete(integration.id)}
                >
                  <IconTrash size={rem(16)} />
                </ActionIcon>
              </Tooltip>
            </Group>
          )}
        </Group>
        {usage}
      </Stack>
    </Card>
  );
}
