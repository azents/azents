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
import { AwsConfigFieldsContainer } from "../AwsConfigFieldsContainer";
import { BraveSearchConfigFieldsContainer } from "../BraveSearchConfigFieldsContainer";
import { GcpConfigFieldsContainer } from "../GcpConfigFieldsContainer";
import { GithubConfigFieldsContainer } from "../GithubConfigFieldsContainer";
import { GitHubUserAuthorizationContainer } from "../GitHubUserAuthorizationContainer";
import { GitHubWizardContainer } from "../GitHubWizardContainer";
import { GoogleAnalyticsConfigFieldsContainer } from "../GoogleAnalyticsConfigFieldsContainer";
import { GoogleSetupContainer } from "../GoogleSetupContainer";
import { KubernetesConfigFieldsContainer } from "../KubernetesConfigFieldsContainer";
import { McpConfigFieldsContainer } from "../McpConfigFieldsContainer";
import { NotionConfigFieldsContainer } from "../NotionConfigFieldsContainer";
import { SentryConfigFieldsContainer } from "../SentryConfigFieldsContainer";
import { toolkitManagementPath } from "../toolkit-owner-scope";
import { ShellConfigFields } from "./ShellConfigFields";
import { ToolkitDisconnectConfirmation } from "./ToolkitDisconnectConfirmation";
import { ToolkitPreparationGuide } from "./ToolkitPreparationGuide";
import { ToolkitSettingsReview } from "./ToolkitSettingsReview";
import setupClasses from "./ToolkitSetup.module.css";
import { ToolkitSetupSection } from "./ToolkitSetupSection";
import { ToolkitTypeIcon } from "./ToolkitTypeIcon";
import type { GitHubFormRegistration } from "../provider-config-views";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitConfigProjection } from "../toolkit-config-projection";
import type {
  PersonalToolkitOrigin,
  ToolkitOwnerScope,
} from "../toolkit-owner-scope";
import type { MutationState, ToolkitConfigFormState } from "../types";
import type { UseFormReturnType } from "@mantine/form";
import type { FormEventHandler, ReactNode } from "react";

export interface ToolkitFormProps {
  navigationOrigin?: PersonalToolkitOrigin;
  githubRegistration: GitHubFormRegistration;
  onComplete?: () => void;
  onAbandonReady?: (abandon: (() => void) | null) => void;
  configProjection: ToolkitConfigProjection;
  configurationFields?: ReactNode;
  scope: ToolkitOwnerScope;
  embedded: boolean;
  toolkitTypeLocked: boolean;
  formState: ToolkitConfigFormState;
  mutationState: MutationState;
  operationPending?: boolean;
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
  oauthDisconnectConfirmation: boolean;
  onAskDisconnectOauth: () => void;
  onDismissDisconnectOauth: () => void;
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
  navigationOrigin,
  githubRegistration,
  onComplete,
  onAbandonReady,
  configProjection,
  configurationFields,
  scope,
  embedded,
  toolkitTypeLocked,
  formState,
  mutationState,
  operationPending = false,
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
  oauthDisconnectConfirmation,
  onAskDisconnectOauth,
  onDismissDisconnectOauth,
  onUserSetupPendingChange,
  onCancel,
}: ToolkitFormProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits");
  const setup = useTranslations("toolkitSetup");
  const scopeKey = JSON.stringify(scope);
  const ownership =
    "owner" in scope ? "user" : scope.agentId != null ? "agent" : "workspace";
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

  if (!isEdit && currentToolSlug === "github") {
    return (
      <>
        {configurationFields ?? (
          <GitHubWizardContainer
            {...scope}
            navigationOrigin={navigationOrigin}
            embedded={embedded}
            initialDescription={form.getValues().description}
            onComplete={onComplete}
            onPendingChange={onUserSetupPendingChange}
            onAbandonReady={onAbandonReady}
          />
        )}
      </>
    );
  }

  if (!isEdit && currentToolSlug === "google") {
    return configurationFields != null ? (
      <>{configurationFields}</>
    ) : (
      <GoogleSetupContainer
        key={`google:${scopeKey}:new`}
        {...scope}
        navigationOrigin={navigationOrigin}
        embedded={embedded}
        initialDescription={form.getValues().description}
        onComplete={onComplete}
        onPendingChange={onUserSetupPendingChange}
        onAbandonReady={onAbandonReady}
      />
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
            <ToolkitSetupSection
              number={1}
              title={setup("prepareTitle")}
              description={setup("prepareDescription")}
            >
              {(isEdit || toolkitTypeLocked) && currentToolSlug ? (
                <Group gap="sm">
                  <ToolkitTypeIcon toolkitType={currentToolSlug} />
                  <Text fw={600}>
                    {toolOptions.find(
                      (option) => option.value === currentToolSlug,
                    )?.label ?? currentToolSlug}
                  </Text>
                </Group>
              ) : (
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
              )}
              <ToolkitPreparationGuide toolkitType={currentToolSlug} />
            </ToolkitSetupSection>

            <ToolkitSetupSection
              number={2}
              title={setup("configureTitle")}
              description={setup("configureDescription")}
            >
              {isEdit && <Text size="sm">{setup("savedHint")}</Text>}
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
                    <McpConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "github" && (
                    <GithubConfigFieldsContainer
                      savedAuthType={githubRegistration.savedAuthType}
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
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "github" &&
                    formState.type === "EDIT" &&
                    githubRegistration.savedUserMode && (
                      <GitHubUserAuthorizationContainer
                        toolkit={formState.config}
                        onPendingChange={onUserSetupPendingChange}
                        context={{
                          ...scope,
                          toolkitId: formState.config.id,
                          returnView: "EDIT",
                          returnPath: toolkitManagementPath(
                            scope,
                            formState.config.id,
                            navigationOrigin,
                          ),
                        }}
                        registrationDirty={githubRegistration.registrationDirty}
                      />
                    )}

                  {currentToolSlug === "notion" && (
                    <NotionConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "sentry" && (
                    <SentryConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "gcp" && (
                    <GcpConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "aws" && (
                    <AwsConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "google_analytics" && (
                    <GoogleAnalyticsConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "google" &&
                    formState.type === "EDIT" && (
                      <GoogleSetupContainer
                        key={`google:${scopeKey}:${formState.config.id}`}
                        {...scope}
                        navigationOrigin={navigationOrigin}
                        toolkitId={formState.config.id}
                        embedded
                        onPendingChange={onUserSetupPendingChange}
                      />
                    )}

                  {currentToolSlug === "brave_search" && (
                    <BraveSearchConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
                    />
                  )}

                  {currentToolSlug === "kubernetes" && (
                    <KubernetesConfigFieldsContainer
                      config={form.getValues().config}
                      onConfigChange={onConfigChange}
                      credentials={form.getValues().credentials ?? null}
                      onCredentialsChange={onCredentialsChange}
                      hasCredentials={
                        formState.type === "EDIT" &&
                        formState.config.has_credentials === true
                      }
                      {...scope}
                      {...(formState.type === "EDIT" && {
                        toolkitConfigId: formState.config.id,
                      })}
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
                          onClick={onAskDisconnectOauth}
                          loading={oauthConnectionPending.disconnect}
                        >
                          {t("oauthConnection.disconnect")}
                        </Button>
                      )}
                    </Group>
                    {oauthDisconnectConfirmation && (
                      <Alert
                        color="red"
                        title={t("oauthConnection.disconnect")}
                      >
                        <ToolkitDisconnectConfirmation
                          personal={ownership === "user"}
                          description=""
                          confirmLabel={t("oauthConnection.disconnect")}
                          cancelLabel={t("cancel")}
                          pending={oauthConnectionPending.disconnect}
                          onConfirm={onDisconnectOauth}
                          onCancel={onDismissDisconnectOauth}
                        />
                      </Alert>
                    )}
                  </Stack>
                </Card>
              )}

              {!isEdit &&
                (currentToolSlug === "notion" ||
                  currentToolSlug === "sentry" ||
                  (currentToolSlug === "mcp" &&
                    form.getValues().config.auth_type === "oauth2")) && (
                  <Alert color="blue">{setup("oauthNext")}</Alert>
                )}
              {currentToolSlug !== "shell" && currentToolSlug !== "google" && (
                <Text size="sm">{setup("testHint")}</Text>
              )}
            </ToolkitSetupSection>

            <ToolkitSetupSection
              number={3}
              title={setup("reviewTitle")}
              description={setup("reviewDescription")}
            >
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
              <Textarea
                label={t("descriptionLabel")}
                placeholder={t("descriptionPlaceholder")}
                key={form.key("description")}
                {...form.getInputProps("description")}
              />
              <details
                className={setupClasses.disclosure}
                open={Boolean(form.errors.slug || form.errors.prompt) || void 0}
              >
                <summary>{setup("advanced")}</summary>
                <Stack gap="md" mt="md">
                  <Text size="sm">{setup("advancedHint")}</Text>
                  <TextInput
                    label={t("slugLabel")}
                    description={
                      ownership !== "agent"
                        ? t("slugDescription")
                        : t("agentSlugDescription")
                    }
                    placeholder={slugPlaceholder || t("slugPlaceholder")}
                    key={form.key("slug")}
                    {...form.getInputProps("slug")}
                  />
                  <Textarea
                    label={t("customPromptLabel")}
                    description={t("customPromptDescription")}
                    placeholder={t("customPromptPlaceholder")}
                    key={form.key("prompt")}
                    {...form.getInputProps("prompt")}
                  />
                </Stack>
              </details>
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
              <ToolkitSettingsReview
                provider={
                  toolOptions.find((option) => option.value === currentToolSlug)
                    ?.label ?? currentToolSlug
                }
                name={form.getValues().name}
                ownership={ownership}
                enabled={form.getValues().enabled}
                alwaysExposeTools={form.getValues().alwaysExposeTools}
              />
              {ownership === "user" && !isEdit && (
                <Text size="sm">{setup("personalAllDefault")}</Text>
              )}
              <Text size="sm">
                {setup(
                  currentToolSlug === "shell" ? "localSaveHint" : "saveHint",
                )}
              </Text>

              {mutationState.type === "IDLE" && mutationState.error && (
                <Alert color="red">{mutationState.error}</Alert>
              )}

              <Group justify="flex-end">
                <Button
                  type="button"
                  variant="default"
                  onClick={onCancel}
                  disabled={
                    operationPending || mutationState.type === "SUBMITTING"
                  }
                >
                  {t("cancel")}
                </Button>
                <Button
                  type="submit"
                  disabled={operationPending}
                  loading={mutationState.type === "SUBMITTING"}
                >
                  {isEdit ? t("save") : t("create")}
                </Button>
              </Group>
            </ToolkitSetupSection>
          </Stack>
        </form>
      </Stack>
    </Container>
  );
}
