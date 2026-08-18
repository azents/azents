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
import { useForm } from "@mantine/form";
import { IconArrowLeft } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useEffect } from "react";
import {
  getArray,
  getString,
  getStringArray,
  isOneOf,
  isRecord,
} from "@/shared/lib/unknown-value";
import { trpc } from "@/trpc/client";
import { toolkitFormSchema } from "../schemas";
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
  ToolkitListState,
} from "../types";

/** Default config initial value by tool */
const DEFAULT_CONFIGS: Record<string, Record<string, unknown>> = {
  shell: { allowed_domains: [], denied_domains: [] },
  mcp: { server_url: "", auth_type: "none", timeout: 30 },
  gcp: {
    project_id: "",
    services: ["logging", "monitoring"],
    writable_services: [],
    timeout: 30,
  },
  aws: {
    region: "us-east-1",
    role_arn: null,
    external_id: null,
    timeout: 30,
  },
  google_analytics: {
    default_property_id: null,
    timeout: 30,
  },
  github: {
    server_url: "https://api.githubcopilot.com/mcp/",
    auth_type: "bearer",
    github_auth_type: "pat",
    toolsets: ["repos", "issues", "pull_requests", "users"],
    timeout: 30,
    inject_runtime_environment: false,
  },
  kubernetes: {
    clusters: [],
    read_only: true,
    allowed_namespaces: null,
    denied_kinds: ["Secret"],
    timeout: 30,
  },
  envvar: {
    entries: [],
  },
};

/** Default credentials initial value by tool */
const DEFAULT_CREDENTIALS: Record<string, Record<string, unknown> | null> = {
  shell: null,
  mcp: { type: "none" },
  gcp: { service_account_key: {} },
  aws: { access_key_id: "", secret_access_key: "" },
  google_analytics: { service_account_key: {} },
  github: { type: "pat" },
  kubernetes: { clusters: {} },
  envvar: { values: {} },
};

const MCP_AUTH_TYPES = ["none", "header", "bearer", "oauth2"] as const;
const GITHUB_AUTH_TYPES = ["pat", "github_app", "github_app_platform"] as const;

function getMcpAuthType(value: unknown): (typeof MCP_AUTH_TYPES)[number] {
  return isOneOf(value, MCP_AUTH_TYPES) ? value : "none";
}

function getGithubAuthType(value: unknown): (typeof GITHUB_AUTH_TYPES)[number] {
  return isOneOf(value, GITHUB_AUTH_TYPES) ? value : "pat";
}

interface ToolkitFormProps {
  handle: string;
  formState: ToolkitConfigFormState;
  mutationState: MutationState;
  scopeListState: ScopeListState;
  toolkitListState: ToolkitListState;
  onSubmit: (values: ToolkitFormValues) => void;
  onAddScope: () => void;
  onDeleteScope: (scopeId: string) => void;
}

export function ToolkitForm({
  handle,
  formState,
  mutationState,
  scopeListState,
  toolkitListState,
  onSubmit,
  onAddScope,
  onDeleteScope,
}: ToolkitFormProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits");

  const isEdit = formState.type === "EDIT";
  const backPath = `/w/${handle}/toolkits`;
  const utils = trpc.useUtils();
  const connectOauthMutation = trpc.toolkit.connectOauth.useMutation();
  const disconnectOauthMutation = trpc.toolkit.disconnectOauth.useMutation({
    onSuccess: () => {
      if (formState.type === "EDIT") {
        void utils.toolkit.getConfig.invalidate({
          handle,
          toolkitId: formState.config.id,
        });
      }
    },
  });

  const form = useForm<ToolkitFormValues>({
    mode: "controlled",
    initialValues: {
      toolkitType: "",
      slug: "",
      name: "",
      description: "",
      prompt: "",
      config: { allowed_domains: [], denied_domains: [] },
      credentials: null,
      enabled: true,
    },
    validate: (values) => {
      const result = toolkitFormSchema.safeParse(values);
      if (result.success) {
        return {};
      }
      const errors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const path = issue.path.join(".");
        if (path && !errors[path]) {
          errors[path] = issue.message;
        }
      }
      return errors;
    },
  });

  // Auto-fill name/description/slug and reset config/credentials on tool selection
  const handleToolSelect = useCallback(
    (toolSlug: string | null) => {
      if (!toolSlug) {
        return;
      }
      form.setFieldValue("toolkitType", toolSlug);

      // Reset config/credentials
      form.setFieldValue("config", DEFAULT_CONFIGS[toolSlug] ?? {});
      form.setFieldValue("credentials", DEFAULT_CREDENTIALS[toolSlug] ?? null);

      // Auto-fill slug in create mode
      if (!isEdit && !form.getValues().slug) {
        form.setFieldValue("slug", toolSlug);
      }

      if (toolkitListState.type === "READY" && !form.getValues().name) {
        const def = toolkitListState.toolkits.find((d) => d.slug === toolSlug);
        if (def) {
          form.setFieldValue("name", def.name);
          form.setFieldValue("description", def.description);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is stable ref
    [toolkitListState, isEdit],
  );

  const handleConnectOauth = useCallback((): void => {
    if (formState.type !== "EDIT") {
      return;
    }
    connectOauthMutation.mutate(
      { handle, toolkitConfigId: formState.config.id },
      {
        onSuccess: (data) => {
          window.open(data.authorization_url, "_blank", "noopener,noreferrer");
        },
      },
    );
  }, [connectOauthMutation, formState, handle]);

  const handleDisconnectOauth = useCallback((): void => {
    if (formState.type !== "EDIT") {
      return;
    }
    disconnectOauthMutation.mutate({
      handle,
      toolkitConfigId: formState.config.id,
    });
  }, [disconnectOauthMutation, formState, handle]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent<unknown>): void => {
      if (
        event.origin !== window.location.origin ||
        formState.type !== "EDIT"
      ) {
        return;
      }
      const data = event.data;
      if (!isRecord(data)) {
        return;
      }
      if (data.type === "azents-oauth-callback") {
        void utils.toolkit.getConfig.invalidate({
          handle,
          toolkitId: formState.config.id,
        });
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [formState, handle, utils.toolkit.getConfig]);

  // Edit mode: set form initial values when Toolkit data loads
  useEffect(() => {
    if (formState.type === "EDIT") {
      const tkConfig = formState.config;
      const rawConfig = tkConfig.config;
      const toolSlug = tkConfig.toolkit_type;

      let config: Record<string, unknown>;
      if (toolSlug === "shell") {
        config = {
          allowed_domains: Array.isArray(rawConfig.allowed_domains)
            ? getStringArray(rawConfig.allowed_domains)
            : [],
          denied_domains: getStringArray(rawConfig.denied_domains),
        };
      } else if (toolSlug === "mcp") {
        const authType = getMcpAuthType(rawConfig.auth_type);
        config = {
          server_url: getString(rawConfig.server_url),
          auth_type: authType,
          timeout:
            typeof rawConfig.timeout === "number" ? rawConfig.timeout : 30,
          header_name: getString(rawConfig.header_name),
          token_url: getString(rawConfig.token_url),
          auth_url: getString(rawConfig.auth_url),
          scopes: getStringArray(rawConfig.scopes),
          discovery_url: getString(rawConfig.discovery_url),
        };
      } else if (toolSlug === "github") {
        const githubAuthType = getGithubAuthType(rawConfig.github_auth_type);
        config = {
          server_url: getString(
            rawConfig.server_url,
            "https://api.githubcopilot.com/mcp/",
          ),
          auth_type:
            rawConfig.auth_type === "bearer" ? rawConfig.auth_type : "bearer",
          github_auth_type: githubAuthType,
          toolsets: Array.isArray(rawConfig.toolsets)
            ? getStringArray(rawConfig.toolsets)
            : ["repos", "issues", "pull_requests", "users"],
          timeout:
            typeof rawConfig.timeout === "number" ? rawConfig.timeout : 30,
          inject_runtime_environment: Boolean(
            rawConfig.inject_runtime_environment,
          ),
        };
      } else if (toolSlug === "envvar") {
        const entries = getArray(rawConfig.entries, isRecord).map((entry) => ({
          name: getString(entry.name),
          masked: typeof entry.masked === "boolean" ? entry.masked : true,
        }));
        config = { entries };
      } else {
        config = rawConfig;
      }

      form.setValues({
        toolkitType: toolSlug,
        slug: tkConfig.slug || toolSlug,
        name: tkConfig.name,
        description: tkConfig.description ?? "",
        prompt: tkConfig.prompt ?? "",
        config,
        credentials:
          toolSlug === "mcp"
            ? { type: getMcpAuthType(rawConfig.auth_type) }
            : toolSlug === "github"
              ? {
                  type: getGithubAuthType(rawConfig.github_auth_type),
                }
              : toolSlug === "envvar"
                ? { values: {} }
                : null,
        enabled: tkConfig.enabled,
      });
      form.resetDirty();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run only on initial load
  }, [formState.type]);

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

  // Tool definition Select options
  const toolOptions =
    toolkitListState.type === "READY"
      ? toolkitListState.toolkits.map((d) => ({
          value: d.slug,
          label: d.name,
        }))
      : [];

  const handleSubmit = form.onSubmit((values) => {
    onSubmit(values);
  });

  const currentToolSlug = form.getValues().toolkitType;

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

        <form onSubmit={handleSubmit}>
          <Stack gap="md">
            <Select
              label={t("toolLabel")}
              placeholder={t("toolPlaceholder")}
              data={toolOptions}
              required
              disabled={isEdit}
              value={form.getValues().toolkitType || null}
              onChange={handleToolSelect}
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
                onChange={(v) => form.setFieldValue("config", v)}
              />
            )}

            {currentToolSlug === "mcp" && (
              <McpConfigFields
                config={form.getValues().config}
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
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
                onConfigChange={(v) => form.setFieldValue("config", v)}
                credentials={form.getValues().credentials ?? null}
                onCredentialsChange={(v) =>
                  form.setFieldValue("credentials", v ?? null)
                }
                hasCredentials={
                  formState.type === "EDIT" &&
                  formState.config.has_credentials === true
                }
              />
            )}

            {formState.type === "EDIT" &&
              ["mcp", "notion", "sentry"].includes(currentToolSlug) &&
              (getString(form.getValues().config.auth_type) === "oauth2" ||
                currentToolSlug === "notion" ||
                currentToolSlug === "sentry") && (
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
                        onClick={handleConnectOauth}
                        loading={connectOauthMutation.isPending}
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
                          onClick={handleDisconnectOauth}
                          loading={disconnectOauthMutation.isPending}
                        >
                          {t("oauthConnection.disconnect")}
                        </Button>
                      )}
                    </Group>
                  </Stack>
                </Card>
              )}

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
