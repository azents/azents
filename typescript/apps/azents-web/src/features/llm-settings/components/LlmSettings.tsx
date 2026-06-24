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
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { IconEdit, IconPlus, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { IntegrationFormModal } from "./IntegrationFormModal";
import { WorkspaceModelSettingsCard } from "./WorkspaceModelSettingsCard";
import type { LlmSettingsContainerOutput } from "../containers/useLlmSettingsContainer";
import type { LlmProviderIntegrationResponse } from "@azents/public-client";

type ProviderLabels = Record<
  | "openai"
  | "anthropic"
  | "google_gemini"
  | "aws_bedrock"
  | "google_vertex_ai"
  | "chatgpt_oauth",
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
    default:
      return provider;
  }
}

export function LlmSettings(
  props: LlmSettingsContainerOutput,
): React.ReactElement {
  const {
    listState,
    formModal,
    mutationState,
    canManage,
    providerOptions,
    modelOptions,
    catalogStates,
    modelsLoading,
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
            <Button leftSection={<IconPlus size={16} />} onClick={onOpenCreate}>
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
            />
          ))}

        <IntegrationFormModal
          handle={props.handle}
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
}: {
  integration: LlmProviderIntegrationResponse;
  canManage: boolean;
  onEdit: (integration: LlmProviderIntegrationResponse) => void;
  onDelete: (id: string) => void;
  onToggleEnabled: (
    integration: LlmProviderIntegrationResponse,
    enabled: boolean,
  ) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");
  const providerLabels: ProviderLabels = {
    openai: t("providers.openai"),
    anthropic: t("providers.anthropic"),
    google_gemini: t("providers.google_gemini"),
    aws_bedrock: t("providers.aws_bedrock"),
    google_vertex_ai: t("providers.google_vertex_ai"),
    chatgpt_oauth: t("providers.chatgpt_oauth"),
  };

  return (
    <Card withBorder padding="md">
      <Group justify="space-between" wrap="nowrap">
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
          <Group gap="xs">
            <Switch
              checked={integration.enabled}
              onChange={(e) =>
                onToggleEnabled(integration, e.currentTarget.checked)
              }
              size="sm"
            />
            <ActionIcon variant="subtle" onClick={() => onEdit(integration)}>
              <IconEdit size={16} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="red"
              onClick={() => onDelete(integration.id)}
            >
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        )}
      </Group>
    </Card>
  );
}
