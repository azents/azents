"use client";

/**
 * Toolkit create/update Full Page form component.
 *
 * Inputs tool selection (Select), name, description, tool-specific settings form, and enabled state.
 */

import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Container,
  Group,
  Loader,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { gitHubUserRegistrationDirty } from "../github-user-credentials";
import { isGitHubUserMode } from "../github-user-oauth-state";
import { GitHubUserAuthorizationPage } from "../GitHubUserAuthorizationPage";
import { AwsConfigFields } from "./AwsConfigFields";
import { BraveSearchConfigFields } from "./BraveSearchConfigFields";
import { EnvVarConfigFields } from "./EnvVarConfigFields";
import { GcpConfigFields } from "./GcpConfigFields";
import { GithubConfigFields } from "./GithubConfigFields";
import { GitHubUserCreation } from "./GitHubUserCreation";
import { GoogleAnalyticsConfigFields } from "./GoogleAnalyticsConfigFields";
import { KubernetesConfigFields } from "./KubernetesConfigFields";
import { McpConfigFields } from "./McpConfigFields";
import { NotionConfigFields } from "./NotionConfigFields";
import { SentryConfigFields } from "./SentryConfigFields";
import { ShellConfigFields } from "./ShellConfigFields";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitConfigProjection } from "../toolkit-config-projection";
import type { MutationState, ToolkitConfigFormState } from "../types";
import type { GitHubUserCreationProps } from "./GitHubUserCreation";
import type { UseFormReturnType } from "@mantine/form";
import type { FormEventHandler, ReactNode } from "react";

export interface ToolkitFormProps {
  githubCreation?: GitHubUserCreationProps;
  configProjection: ToolkitConfigProjection;
  configurationFields?: ReactNode;
  handle: string;
  agentId?: string;
  embedded: boolean;
  toolkitTypeLocked: boolean;
  formState: ToolkitConfigFormState;
  mutationState: MutationState;
  form: UseFormReturnType<ToolkitFormValues>;
  isEdit: boolean;
  backPath: string;
  toolOptions: Array<{ value: string; label: string }>;
  currentToolSlug: string;
  namePlaceholder: string;
  slugPlaceholder: string;
  nameRequired: boolean;
  showOauthConnection: boolean;
  oauthConnectionPending: {
    connect: boolean;
    disconnect: boolean;
  };
  onSubmit: FormEventHandler<HTMLFormElement>;
  onToolSelect: (toolSlug: string | null) => void;
  onConfigChange: (config: Record<string, unknown>) => void;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  onConnectOauth: () => void;
  onDisconnectOauth: () => void;
  onUserSetupPendingChange?: (pending: boolean) => void;
  onCancel: () => void;
}

function oauthConnectionStatusTranslationKey(
  status: string | null,
):
  | "statusNotConnected"
  | "statusConnected"
  | "statusReconnectRequired"
  | "statusUnknown" {
  switch (status) {
    case null:
      return "statusNotConnected";
    case "connected":
      return "statusConnected";
    case "reconnect_required":
      return "statusReconnectRequired";
    default:
      return "statusUnknown";
  }
}

export function ToolkitForm({
  githubCreation,
  configProjection,
  configurationFields,
  handle,
  agentId,
  embedded,
  toolkitTypeLocked,
  formState,
  mutationState,
  form,
  isEdit,
  backPath,
  toolOptions,
  currentToolSlug,
  namePlaceholder,
  slugPlaceholder,
  nameRequired,
  showOauthConnection,
  oauthConnectionPending,
  onSubmit,
  onToolSelect,
  onConfigChange,
  onCredentialsChange,
  onConnectOauth,
  onDisconnectOauth,
  onUserSetupPendingChange,
  onCancel,
}: ToolkitFormProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits");
  const handleSubmit: FormEventHandler<HTMLFormElement> = (event) => {
    event.stopPropagation();
    onSubmit(event);
  };

  if (formState.type === "LOADING") {
    return (
      <Container size="md" py="xl">
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      </Container>
    );
  }

  if (formState.type === "NOT_FOUND") {
    return (
      <Container size="md" py="xl">
        <Alert color="red">{t("notFound")}</Alert>
      </Container>
    );
  }

  if (
    githubCreation != null &&
    githubCreation.state.type !== "IDLE" &&
    !(
      githubCreation.state.type === "ERROR" &&
      githubCreation.state.attemptId == null
    )
  ) {
    return (
      <Container size="md" py={embedded ? 0 : "xl"}>
        <Stack gap="lg">
          <Title order={3}>{t("createTitle")}</Title>
          <GitHubUserCreation {...githubCreation} />
        </Stack>
      </Container>
    );
  }

  return (
    <Container
      size="md"
      w="100%"
      miw={0}
      py={embedded ? 0 : "xl"}
      px={embedded ? 0 : "md"}
    >
      <Stack gap="lg">
        {!embedded && (
          <Anchor component={Link} href={backPath} size="sm">
            <Group gap={4}>
              <IconArrowLeft size={14} />
              {t("backToList")}
            </Group>
          </Anchor>
        )}

        <Title order={3}>{isEdit ? t("editTitle") : t("createTitle")}</Title>

        <form onSubmit={handleSubmit}>
          <Stack gap="md">
            <Select
              label={t("toolLabel")}
              placeholder={t("toolPlaceholder")}
              data={toolOptions}
              required
              disabled={isEdit || toolkitTypeLocked}
              value={form.getValues().toolkitType || null}
              onChange={onToolSelect}
              error={form.errors.toolkitType}
            />

            <TextInput
              label={t("nameLabel")}
              placeholder={
                currentToolSlug === "mcp"
                  ? t("mcpNamePlaceholder")
                  : namePlaceholder
              }
              required={nameRequired}
              key={form.key("name")}
              {...form.getInputProps("name")}
            />

            <TextInput
              label={t("slugLabel")}
              description={
                agentId == null
                  ? t("slugDescription")
                  : t("agentSlugDescription")
              }
              placeholder={slugPlaceholder || t("slugPlaceholder")}
              key={form.key("slug")}
              {...form.getInputProps("slug")}
            />

            <Textarea
              label={t("descriptionLabel")}
              placeholder={t("descriptionPlaceholder")}
              key={form.key("description")}
              {...form.getInputProps("description")}
            />

            <Textarea
              label={t("customPromptLabel")}
              description={t("customPromptDescription")}
              placeholder={t("customPromptPlaceholder")}
              key={form.key("prompt")}
              {...form.getInputProps("prompt")}
            />

            {/* Tool-specific settings form */}
            {configurationFields !== void 0 ? (
              configurationFields
            ) : (
              <>
                {currentToolSlug === "shell" && (
                  <ShellConfigFields
                    value={{
                      allowed_domains:
                        configProjection.type === "shell"
                          ? configProjection.config.allowed_domains
                          : [],
                      denied_domains:
                        configProjection.type === "shell"
                          ? configProjection.config.denied_domains
                          : [],
                    }}
                    onChange={onConfigChange}
                  />
                )}

                {currentToolSlug === "mcp" && (
                  <McpConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "github" && (
                  <GithubConfigFields
                    savedAuthType={
                      formState.type === "EDIT"
                        ? String(formState.config.config.github_auth_type)
                        : void 0
                    }
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    authorizationState={
                      formState.type === "EDIT"
                        ? (formState.config.authorization_state ?? null)
                        : null
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "github" &&
                  formState.type === "EDIT" &&
                  isGitHubUserMode(
                    formState.config.config.github_auth_type,
                  ) && (
                    <GitHubUserAuthorizationPage
                      toolkit={formState.config}
                      onPendingChange={onUserSetupPendingChange}
                      context={{
                        handle,
                        toolkitId: formState.config.id,
                        agentId,
                        returnView: "EDIT",
                        returnPath:
                          agentId == null
                            ? `/w/${handle}/toolkits/${formState.config.id}/edit`
                            : `/w/${handle}/agents/${agentId}/settings/capabilities#agent-toolkits`,
                      }}
                      registrationDirty={gitHubUserRegistrationDirty(
                        formState.config.config.github_auth_type,
                        form.getValues().config.github_auth_type,
                        form.getValues().credentials ?? null,
                      )}
                    />
                  )}

                {currentToolSlug === "notion" && (
                  <NotionConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "sentry" && (
                  <SentryConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "gcp" && (
                  <GcpConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "aws" && (
                  <AwsConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "google_analytics" && (
                  <GoogleAnalyticsConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "brave_search" && (
                  <BraveSearchConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "kubernetes" && (
                  <KubernetesConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                    handle={handle}
                    {...(agentId != null && { agentId })}
                    {...(formState.type === "EDIT" && {
                      toolkitConfigId: formState.config.id,
                    })}
                  />
                )}

                {currentToolSlug === "envvar" && (
                  <EnvVarConfigFields
                    config={form.getValues().config}
                    onConfigChange={onConfigChange}
                    credentials={form.getValues().credentials ?? null}
                    onCredentialsChange={onCredentialsChange}
                    hasCredentials={
                      formState.type === "EDIT" &&
                      formState.config.has_credentials === true
                    }
                  />
                )}
              </>
            )}

            {formState.type === "EDIT" && showOauthConnection && (
              <Card withBorder>
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={600}>{t("oauthConnection.title")}</Text>
                    <Badge>
                      {t(
                        `oauthConnection.${oauthConnectionStatusTranslationKey(
                          formState.config.oauth_connection?.status ?? null,
                        )}`,
                      )}
                    </Badge>
                  </Group>
                  {formState.config.oauth_connection?.issuer != null && (
                    <Text size="sm" c="dimmed">
                      {t("oauthConnection.issuer")}:{" "}
                      {formState.config.oauth_connection.issuer}
                    </Text>
                  )}
                  {formState.config.oauth_connection?.resource != null && (
                    <Text size="sm" c="dimmed">
                      {t("oauthConnection.resource")}:{" "}
                      {formState.config.oauth_connection.resource}
                    </Text>
                  )}
                  {formState.config.oauth_connection?.scope != null && (
                    <Text size="sm" c="dimmed">
                      {t("oauthConnection.scope")}:{" "}
                      {formState.config.oauth_connection.scope}
                    </Text>
                  )}
                  {formState.config.oauth_connection?.expires_at != null && (
                    <Text size="sm" c="dimmed">
                      {t("oauthConnection.expiresAt")}:{" "}
                      {formState.config.oauth_connection.expires_at}
                    </Text>
                  )}
                  <Group>
                    <Button
                      type="button"
                      variant="light"
                      onClick={onConnectOauth}
                      loading={oauthConnectionPending.connect}
                    >
                      {formState.config.oauth_connection == null
                        ? t("oauthConnection.connect")
                        : t("oauthConnection.reconnect")}
                    </Button>
                    {formState.config.oauth_connection != null && (
                      <Button
                        type="button"
                        variant="subtle"
                        color="red"
                        onClick={onDisconnectOauth}
                        loading={oauthConnectionPending.disconnect}
                      >
                        {t("oauthConnection.disconnect")}
                      </Button>
                    )}
                  </Group>
                </Stack>
              </Card>
            )}

            <Switch
              label={t("alwaysExposeToolsLabel")}
              description={t("alwaysExposeToolsDescription")}
              key={form.key("alwaysExposeTools")}
              {...form.getInputProps("alwaysExposeTools", {
                type: "checkbox",
              })}
            />

            <Switch
              label={t("enabledLabel")}
              key={form.key("enabled")}
              {...form.getInputProps("enabled", { type: "checkbox" })}
            />

            {mutationState.type === "IDLE" && mutationState.error && (
              <Alert color="red">{mutationState.error}</Alert>
            )}
            {githubCreation?.state.type === "ERROR" && (
              <GitHubUserCreation {...githubCreation} />
            )}

            <Group justify="flex-end">
              <Button
                type="button"
                variant="default"
                onClick={onCancel}
                disabled={mutationState.type === "SUBMITTING"}
              >
                {t("cancel")}
              </Button>
              <Button
                type="submit"
                loading={mutationState.type === "SUBMITTING"}
              >
                {isEdit
                  ? t("save")
                  : currentToolSlug === "github" &&
                      isGitHubUserMode(form.getValues().config.github_auth_type)
                    ? t("github.user.authorize")
                    : t("create")}
              </Button>
            </Group>
          </Stack>
        </form>
      </Stack>
    </Container>
  );
}
