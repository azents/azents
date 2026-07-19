"use client";

/**
 * LLM Provider Integration create/update modal.
 *
 * Manages provider selection (CREATE) and alias input,
 * and renders provider-specific form sub-components.
 */

import {
  Alert,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  TextInput,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { KimiOAuthConnectionCardContainer } from "../containers/KimiOAuthConnectionCardContainer";
import { ApiKeyForm } from "./ApiKeyForm";
import { AwsCredentialsForm } from "./AwsCredentialsForm";
import { ChatGPTOAuthConnectionCard } from "./ChatGPTOAuthConnectionCard";
import { GcpServiceAccountForm } from "./GcpServiceAccountForm";
import { SetupGuide } from "./SetupGuide";
import { XaiOAuthConnectionCard } from "./XaiOAuthConnectionCard";
import type { LlmSettingsContainerOutput } from "../containers/useLlmSettingsContainer";
import type { CredentialType } from "./SetupGuide";
import type { LlmProviderIntegrationResponse } from "@azents/public-client";

const PROVIDER_VALUES = [
  "openai",
  "anthropic",
  "google_gemini",
  "aws_bedrock",
  "google_vertex_ai",
  "chatgpt_oauth",
  "xai",
  "xai_oauth",
  "kimi_oauth",
  "openrouter",
] as const;

type ProviderValue = (typeof PROVIDER_VALUES)[number];
type ProviderLabels = Record<ProviderValue, string>;

/** Determine credential type by provider */
export function credentialTypeForProvider(provider: string): CredentialType {
  switch (provider) {
    case "aws_bedrock":
      return "aws_credentials";
    case "google_vertex_ai":
      return "gcp_service_account";
    default:
      return "api_key";
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
    case "kimi_oauth":
      return labels.kimi_oauth;
    case "openrouter":
      return labels.openrouter;
    default:
      return provider;
  }
}

/** Common Props for provider-specific forms */
export interface ProviderFormProps {
  name: string;
  provider: string | null;
  integration: LlmProviderIntegrationResponse | null;
  isCreate: boolean;
  isSubmitting: boolean;
  onCreate: LlmSettingsContainerOutput["onCreate"];
  onUpdate: LlmSettingsContainerOutput["onUpdate"];
  onClose: () => void;
}

export function IntegrationFormModal({
  handle,
  availableProviderValues,
  formModal,
  mutationState,
  onClose,
  onCreate,
  onUpdate,
}: {
  handle: string;
  availableProviderValues: string[];
  formModal: LlmSettingsContainerOutput["formModal"];
  mutationState: LlmSettingsContainerOutput["mutationState"];
  onClose: () => void;
  onCreate: LlmSettingsContainerOutput["onCreate"];
  onUpdate: LlmSettingsContainerOutput["onUpdate"];
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");
  const isOpen = formModal.type !== "CLOSED";
  const isCreate = formModal.type === "CREATE";

  // Remount form by key: integration id for EDIT, "create" for CREATE
  const contentKey =
    formModal.type === "EDIT" ? formModal.integration.id : "create";

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={isCreate ? t("createTitle") : t("editTitle")}
    >
      <IntegrationFormContent
        key={contentKey}
        handle={handle}
        availableProviderValues={availableProviderValues}
        formModal={formModal}
        mutationState={mutationState}
        onClose={onClose}
        onCreate={onCreate}
        onUpdate={onUpdate}
      />
    </Modal>
  );
}

/** Modal internal content — remounted by key prop */
function IntegrationFormContent({
  handle,
  availableProviderValues,
  formModal,
  mutationState,
  onClose,
  onCreate,
  onUpdate,
}: {
  handle: string;
  availableProviderValues: string[];
  formModal: LlmSettingsContainerOutput["formModal"];
  mutationState: LlmSettingsContainerOutput["mutationState"];
  onClose: () => void;
  onCreate: LlmSettingsContainerOutput["onCreate"];
  onUpdate: LlmSettingsContainerOutput["onUpdate"];
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
    kimi_oauth: t("providers.kimi_oauth"),
    openrouter: t("providers.openrouter"),
  };
  const availableProviders = new Set(availableProviderValues);
  const providerOptions = PROVIDER_VALUES.filter((value) =>
    availableProviders.has(value),
  ).map((value) => ({
    value,
    label: providerLabels[value],
  }));
  const isCreate = formModal.type === "CREATE";
  const isSubmitting = mutationState.type === "SUBMITTING";

  const [provider, setProvider] = useState<string | null>(
    formModal.type === "EDIT" ? formModal.integration.provider : null,
  );
  const [name, setName] = useState(
    formModal.type === "EDIT" ? formModal.integration.name : "",
  );

  const credType = credentialTypeForProvider(provider ?? "");
  const integration = formModal.type === "EDIT" ? formModal.integration : null;
  const providerDisplayName = provider
    ? labelForProvider(provider, providerLabels)
    : "";
  const isChatGPTOAuth = provider === "chatgpt_oauth";
  const isXaiOAuth = provider === "xai_oauth";
  const isKimiOAuth = provider === "kimi_oauth";
  const kimiConnectionStatus =
    integration?.config?.type === "kimi_oauth"
      ? integration.config.status
      : null;
  const isOAuthProvider = isChatGPTOAuth || isXaiOAuth || isKimiOAuth;

  const formProps: ProviderFormProps = {
    name,
    provider,
    integration,
    isCreate,
    isSubmitting,
    onCreate,
    onUpdate,
    onClose,
  };

  return (
    <Stack gap="md">
      {mutationState.type === "IDLE" && mutationState.error && (
        <Alert color="red">{mutationState.error}</Alert>
      )}
      {isCreate && (
        <Select
          label={t("providerLabel")}
          placeholder={t("providerPlaceholder")}
          data={providerOptions}
          value={provider}
          onChange={setProvider}
          required
        />
      )}
      {!(isCreate && isOAuthProvider) && (
        <TextInput
          label={t("nameLabel")}
          placeholder={
            isCreate && providerDisplayName
              ? providerDisplayName
              : t("namePlaceholder")
          }
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
      )}

      {/* Provider-specific forms (each owns useForm) */}
      {isChatGPTOAuth && isCreate && (
        <ChatGPTOAuthConnectionCard
          handle={handle}
          canManage
          onConnected={onClose}
        />
      )}
      {isXaiOAuth && isCreate && (
        <XaiOAuthConnectionCard
          handle={handle}
          canManage
          onConnected={onClose}
        />
      )}
      {isKimiOAuth && (
        <KimiOAuthConnectionCardContainer
          handle={handle}
          canManage
          connectionStatus={kimiConnectionStatus}
          reconnect={!isCreate}
          onConnected={onClose}
        />
      )}
      {isOAuthProvider && !isCreate && (
        <OAuthAliasForm
          name={name}
          isSubmitting={isSubmitting}
          onUpdate={onUpdate}
          onClose={onClose}
        />
      )}
      {credType === "api_key" && !isOAuthProvider && (
        <ApiKeyForm {...formProps} />
      )}
      {credType === "aws_credentials" && <AwsCredentialsForm {...formProps} />}
      {credType === "gcp_service_account" && (
        <GcpServiceAccountForm {...formProps} />
      )}

      {/* Setup guide */}
      {provider && !isOAuthProvider && (
        <SetupGuide credType={credType} provider={provider} />
      )}
    </Stack>
  );
}

function OAuthAliasForm({
  name,
  isSubmitting,
  onUpdate,
  onClose,
}: {
  name: string;
  isSubmitting: boolean;
  onUpdate: LlmSettingsContainerOutput["onUpdate"];
  onClose: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!name) {
      return;
    }
    onUpdate({ name });
  }

  return (
    <form onSubmit={handleSubmit}>
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          {t("cancel")}
        </Button>
        <Button type="submit" loading={isSubmitting}>
          {t("save")}
        </Button>
      </Group>
    </form>
  );
}
