"use client";

/**
 * Toolkit create/update Full Page form component.
 *
 * Inputs tool selection (Select), name, description, tool-specific settings form, and enabled state.
 * Scope management section is added in edit mode.
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
import { getStringArray } from "@/shared/lib/unknown-value";
import { AwsConfigFields } from "./AwsConfigFields";
import { EnvVarConfigFields } from "./EnvVarConfigFields";
import { GcpConfigFields } from "./GcpConfigFields";
import { GithubConfigFields } from "./GithubConfigFields";
import { GoogleAnalyticsConfigFields } from "./GoogleAnalyticsConfigFields";
import { KubernetesConfigFields } from "./KubernetesConfigFields";
import { McpConfigFields } from "./McpConfigFields";
import { NotionConfigFields } from "./NotionConfigFields";
import { SentryConfigFields } from "./SentryConfigFields";
import { ShellConfigFields } from "./ShellConfigFields";
import { ToolkitScopeSection } from "./ToolkitScopeSection";
import type { ToolkitFormValues } from "../schemas";
import type {
  MutationState,
  ScopeListState,
  ToolkitConfigFormState,
} from "../types";
import type { UseFormReturnType } from "@mantine/form";
import type { FormEventHandler } from "react";

export interface ToolkitFormProps {
  handle: string;
  formState: ToolkitConfigFormState;
  mutationState: MutationState;
  scopeListState: ScopeListState;
  form: UseFormReturnType<ToolkitFormValues>;
  isEdit: boolean;
  backPath: string;
  toolOptions: Array<{ value: string; label: string }>;
  currentToolSlug: string;
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
  onAddScope: () => void;
  onDeleteScope: (scopeId: string) => void;
}

export function ToolkitForm({
  handle,
  formState,
  mutationState,
  scopeListState,
  form,
  isEdit,
  backPath,
  toolOptions,
  currentToolSlug,
  showOauthConnection,
  oauthConnectionPending,
  onSubmit,
  onToolSelect,
  onConfigChange,
  onCredentialsChange,
  onConnectOauth,
  onDisconnectOauth,
  onAddScope,
  onDeleteScope,
}: ToolkitFormProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits");

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

  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <Anchor component={Link} href={backPath} size="sm">
          <Group gap={4}>
            <IconArrowLeft size={14} />
            {t("backToList")}
          </Group>
        </Anchor>

        <Title order={3}>{isEdit ? t("editTitle") : t("createTitle")}</Title>

        <form onSubmit={onSubmit}>
          <Stack gap="md">
            <Select
              label={t("toolLabel")}
              placeholder={t("toolPlaceholder")}
              data={toolOptions}
              required
              disabled={isEdit}
              value={form.getValues().toolkitType || null}
              onChange={onToolSelect}
              error={form.errors.toolkitType}
            />

            <TextInput
              label={t("slugLabel")}
              description={t("slugDescription")}
              placeholder={t("slugPlaceholder")}
              required
              key={form.key("slug")}
              {...form.getInputProps("slug")}
            />

            <TextInput
              label={t("nameLabel")}
              required
              key={form.key("name")}
              {...form.getInputProps("name")}
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
            {currentToolSlug === "shell" && (
              <ShellConfigFields
                value={{
                  allowed_domains: getStringArray(
                    form.getValues().config.allowed_domains,
                  ),
                  denied_domains: getStringArray(
                    form.getValues().config.denied_domains,
                  ),
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
                {...(formState.type === "EDIT" && {
                  toolkitConfigId: formState.config.id,
                })}
              />
            )}

            {currentToolSlug === "github" && (
              <GithubConfigFields
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
                {...(formState.type === "EDIT" && {
                  toolkitConfigId: formState.config.id,
                })}
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

            {formState.type === "EDIT" && showOauthConnection && (
              <Card withBorder>
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={600}>{t("oauthConnection.title")}</Text>
                    <Badge>
                      {formState.config.oauth_connection?.status ??
                        "not_connected"}
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

            {/* Scope section (edit mode only) */}
            {isEdit && (
              <ToolkitScopeSection
                scopeListState={scopeListState}
                onAddScope={onAddScope}
                onDeleteScope={onDeleteScope}
              />
            )}

            {mutationState.type === "IDLE" && mutationState.error && (
              <Alert color="red">{mutationState.error}</Alert>
            )}

            <Group justify="flex-end">
              <Button component={Link} href={backPath} variant="default">
                {t("cancel")}
              </Button>
              <Button
                type="submit"
                loading={mutationState.type === "SUBMITTING"}
              >
                {isEdit ? t("save") : t("create")}
              </Button>
            </Group>
          </Stack>
        </form>
      </Stack>
    </Container>
  );
}
