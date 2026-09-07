"use client";

/**
 * Toolkit create/update form container hook.
 *
 * Edit mode when toolkitId exists; creates the form state, performs API work,
 * and owns the behavioral callbacks consumed by the ToolkitForm view.
 */

import { useForm, type UseFormReturnType } from "@mantine/form";
import { useWindowEvent } from "@mantine/hooks";
import { useRouter } from "next/navigation";
import {
  type FormEventHandler,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  getArray,
  getString,
  getStringArray,
  isOneOf,
  isRecord,
} from "@/shared/lib/unknown-value";
import { trpc } from "@/trpc/client";
import { toolkitFormSchema } from "../schemas";
import type { ToolkitFormValues } from "../schemas";
import type {
  MutationState,
  ScopeListState,
  ToolkitConfigFormState,
  ToolkitListState,
} from "../types";

export interface ToolkitFormContainerProps {
  handle: string;
  toolkitId?: string;
  agentId?: string;
  embedded?: boolean;
  onComplete?: () => void;
  initialToolkitType?: string;
}

export interface ToolkitFormContainerOutput {
  handle: string;
  agentId?: string;
  embedded: boolean;
  toolkitTypeLocked: boolean;
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
  onCancel: () => void;
}

/** Default config initial value by tool. */
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

/** Default credentials initial value by tool. */
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

/**
 * Return null when all secret values in credentials dict are empty.
 * Used to keep existing credentials in edit mode.
 */
function normalizeCredentials(
  credentials: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (credentials == null) {
    return null;
  }

  const secretEntries = Object.entries(credentials).filter(
    ([key]) => key !== "type",
  );
  if (secretEntries.length === 0) {
    return null;
  }
  const allEmpty = secretEntries.every(
    ([, value]) => value === "" || value == null,
  );
  return allEmpty ? null : credentials;
}

export function useToolkitFormContainer(
  props: ToolkitFormContainerProps,
): ToolkitFormContainerOutput {
  const {
    handle,
    toolkitId,
    agentId,
    embedded = false,
    onComplete,
    initialToolkitType,
  } = props;
  const router = useRouter();
  const utils = trpc.useUtils();
  const isEditMode = toolkitId != null;
  const backPath =
    agentId == null
      ? `/w/${handle}/toolkits`
      : `/w/${handle}/agents/${agentId}/settings/capabilities#agent-toolkits`;
  const form = useForm<ToolkitFormValues>({
    mode: "controlled",
    initialValues: {
      toolkitType: initialToolkitType ?? "",
      slug: initialToolkitType ?? "",
      name: "",
      description: "",
      prompt: "",
      config:
        initialToolkitType == null
          ? { allowed_domains: [], denied_domains: [] }
          : (DEFAULT_CONFIGS[initialToolkitType] ?? {}),
      credentials:
        initialToolkitType == null
          ? null
          : (DEFAULT_CREDENTIALS[initialToolkitType] ?? null),
      enabled: true,
      alwaysExposeTools: false,
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
  const [mutationState, setMutationState] = useState<MutationState>({
    type: "IDLE",
    error: null,
  });

  const definitionsQuery = trpc.toolkit.listToolkits.useQuery();
  const workspaceToolkitQuery = trpc.toolkit.getConfig.useQuery(
    { handle, toolkitId: toolkitId ?? "" },
    { enabled: isEditMode && agentId == null },
  );
  const agentToolkitQuery = trpc.toolkit.getAgentConfig.useQuery(
    { handle, agentId: agentId ?? "", toolkitConfigId: toolkitId ?? "" },
    { enabled: isEditMode && agentId != null },
  );
  const scopesQuery = trpc.toolkit.listScopes.useQuery(
    { handle, toolkitId: toolkitId ?? "" },
    { enabled: isEditMode && agentId == null },
  );
  const toolkitQuery =
    agentId == null ? workspaceToolkitQuery : agentToolkitQuery;

  const toolkitListState: ToolkitListState = useMemo(() => {
    if (definitionsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (definitionsQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", toolkits: definitionsQuery.data?.items ?? [] };
  }, [
    definitionsQuery.data,
    definitionsQuery.isError,
    definitionsQuery.isLoading,
  ]);
  useEffect(() => {
    if (
      initialToolkitType == null ||
      toolkitListState.type !== "READY" ||
      form.getValues().name
    ) {
      return;
    }
    const definition = toolkitListState.toolkits.find(
      (toolkit) => toolkit.slug === initialToolkitType,
    );
    if (definition) {
      form.setFieldValue("name", definition.name);
      form.setFieldValue("description", definition.description);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is a stable Mantine ref.
  }, [initialToolkitType, toolkitListState]);

  const formState: ToolkitConfigFormState = useMemo(() => {
    if (!isEditMode) {
      return { type: "CREATE" };
    }
    if (toolkitQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (toolkitQuery.isError || !toolkitQuery.data) {
      return { type: "NOT_FOUND" };
    }
    return { type: "EDIT", config: toolkitQuery.data };
  }, [
    isEditMode,
    toolkitQuery.data,
    toolkitQuery.isError,
    toolkitQuery.isLoading,
  ]);

  const scopeListState: ScopeListState = useMemo(() => {
    if (!isEditMode || agentId != null) {
      return { type: "READY", scopes: [] };
    }
    if (scopesQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (scopesQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", scopes: scopesQuery.data?.items ?? [] };
  }, [
    agentId,
    isEditMode,
    scopesQuery.data,
    scopesQuery.isError,
    scopesQuery.isLoading,
  ]);

  const createMutation = trpc.toolkit.createConfig.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      void utils.toolkit.listConfigs.invalidate({ handle });
      if (embedded) {
        onComplete?.();
      } else {
        router.push(backPath);
      }
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const updateMutation = trpc.toolkit.updateConfig.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      void utils.toolkit.listConfigs.invalidate({ handle });
      if (toolkitId) {
        void utils.toolkit.getConfig.invalidate({ handle, toolkitId });
      }
      if (embedded) {
        onComplete?.();
      } else {
        router.push(backPath);
      }
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const createAgentMutation = trpc.toolkit.createAgentConfig.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      if (agentId) {
        void utils.toolkit.listAgentManagement.invalidate({ handle, agentId });
      }
      onComplete?.();
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const updateAgentMutation = trpc.toolkit.updateAgentConfig.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      if (agentId) {
        void utils.toolkit.listAgentManagement.invalidate({ handle, agentId });
      }
      if (agentId && toolkitId) {
        void utils.toolkit.getAgentConfig.invalidate({
          handle,
          agentId,
          toolkitConfigId: toolkitId,
        });
      }
      onComplete?.();
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const createScopeMutation = trpc.toolkit.createScope.useMutation({
    onSuccess: () => {
      if (toolkitId) {
        void utils.toolkit.listScopes.invalidate({ handle, toolkitId });
      }
    },
  });
  const deleteScopeMutation = trpc.toolkit.deleteScope.useMutation({
    onSuccess: () => {
      if (toolkitId) {
        void utils.toolkit.listScopes.invalidate({ handle, toolkitId });
      }
    },
  });
  const connectOauthMutation = trpc.toolkit.connectOauth.useMutation();
  const connectAgentOauthMutation =
    trpc.toolkit.connectAgentOauth.useMutation();
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
  const disconnectAgentOauthMutation =
    trpc.toolkit.disconnectAgentOauth.useMutation({
      onSuccess: () => {
        if (agentId && toolkitId) {
          void utils.toolkit.getAgentConfig.invalidate({
            handle,
            agentId,
            toolkitConfigId: toolkitId,
          });
          void utils.toolkit.listAgentManagement.invalidate({
            handle,
            agentId,
          });
        }
      },
    });

  const submitForm = useCallback(
    (values: ToolkitFormValues): void => {
      setMutationState({ type: "SUBMITTING" });
      const credentials = normalizeCredentials(values.credentials ?? null);

      if (agentId) {
        if (isEditMode && toolkitId) {
          updateAgentMutation.mutate({
            handle,
            agentId,
            toolkitConfigId: toolkitId,
            slug: values.slug,
            name: values.name,
            description: values.description ?? null,
            prompt: values.prompt ?? null,
            config: values.config,
            ...(credentials != null && { credentials }),
            enabled: values.enabled,
            alwaysExposeTools: values.alwaysExposeTools,
          });
          return;
        }
        createAgentMutation.mutate({
          handle,
          agentId,
          toolkitType: values.toolkitType,
          slug: values.slug,
          name: values.name,
          description: values.description,
          prompt: values.prompt,
          config: values.config,
          ...(credentials != null && { credentials }),
          enabled: values.enabled,
          alwaysExposeTools: values.alwaysExposeTools,
        });
        return;
      }

      if (isEditMode && toolkitId) {
        updateMutation.mutate({
          handle,
          toolkitId,
          slug: values.slug,
          name: values.name,
          description: values.description ?? null,
          prompt: values.prompt ?? null,
          config: values.config,
          ...(credentials != null && { credentials }),
          enabled: values.enabled,
          alwaysExposeTools: values.alwaysExposeTools,
        });
        return;
      }

      createMutation.mutate({
        handle,
        toolkitType: values.toolkitType,
        slug: values.slug,
        name: values.name,
        description: values.description,
        prompt: values.prompt,
        config: values.config,
        ...(credentials != null && { credentials }),
        enabled: values.enabled,
        alwaysExposeTools: values.alwaysExposeTools,
      });
    },
    [
      agentId,
      createAgentMutation,
      createMutation,
      handle,
      isEditMode,
      toolkitId,
      updateAgentMutation,
      updateMutation,
    ],
  );
  const onSubmit: FormEventHandler<HTMLFormElement> = form.onSubmit(submitForm);

  const onToolSelect = useCallback(
    (toolSlug: string | null): void => {
      if (!toolSlug) {
        return;
      }
      form.setFieldValue("toolkitType", toolSlug);
      form.setFieldValue("config", DEFAULT_CONFIGS[toolSlug] ?? {});
      form.setFieldValue("credentials", DEFAULT_CREDENTIALS[toolSlug] ?? null);

      if (!isEditMode && !form.getValues().slug) {
        form.setFieldValue("slug", toolSlug);
      }
      if (toolkitListState.type === "READY" && !form.getValues().name) {
        const definition = toolkitListState.toolkits.find(
          (toolkit) => toolkit.slug === toolSlug,
        );
        if (definition) {
          form.setFieldValue("name", definition.name);
          form.setFieldValue("description", definition.description);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is a stable Mantine ref.
    [isEditMode, toolkitListState],
  );
  const onConfigChange = useCallback(
    (config: Record<string, unknown>): void => {
      form.setFieldValue("config", config);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is a stable Mantine ref.
    [],
  );
  const onCredentialsChange = useCallback(
    (credentials: Record<string, unknown> | null): void => {
      form.setFieldValue("credentials", credentials);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is a stable Mantine ref.
    [],
  );
  const onConnectOauth = useCallback((): void => {
    if (formState.type !== "EDIT") {
      return;
    }
    if (agentId) {
      connectAgentOauthMutation.mutate(
        {
          handle,
          agentId,
          toolkitConfigId: formState.config.id,
        },
        {
          onSuccess: (data) => {
            window.open(
              data.authorization_url,
              "mcp-oauth-popup",
              "width=1024,height=768",
            );
          },
        },
      );
      return;
    }
    connectOauthMutation.mutate(
      { handle, toolkitConfigId: formState.config.id },
      {
        onSuccess: (data) => {
          window.open(
            data.authorization_url,
            "mcp-oauth-popup",
            "width=1024,height=768",
          );
        },
      },
    );
  }, [
    agentId,
    connectAgentOauthMutation,
    connectOauthMutation,
    formState,
    handle,
  ]);
  const onDisconnectOauth = useCallback((): void => {
    if (formState.type !== "EDIT") {
      return;
    }
    if (agentId) {
      disconnectAgentOauthMutation.mutate({
        handle,
        agentId,
        toolkitConfigId: formState.config.id,
      });
      return;
    }
    disconnectOauthMutation.mutate({
      handle,
      toolkitConfigId: formState.config.id,
    });
  }, [
    agentId,
    disconnectAgentOauthMutation,
    disconnectOauthMutation,
    formState,
    handle,
  ]);

  const handleOauthCallbackMessage = useCallback(
    (event: MessageEvent<unknown>): void => {
      if (
        event.origin !== window.location.origin ||
        formState.type !== "EDIT" ||
        !isRecord(event.data) ||
        event.data.type !== "azents-oauth-callback"
      ) {
        return;
      }
      if (agentId) {
        void utils.toolkit.getAgentConfig.invalidate({
          handle,
          agentId,
          toolkitConfigId: formState.config.id,
        });
        void utils.toolkit.listAgentManagement.invalidate({ handle, agentId });
      } else {
        void utils.toolkit.getConfig.invalidate({
          handle,
          toolkitId: formState.config.id,
        });
      }
    },
    [
      agentId,
      formState,
      handle,
      utils.toolkit.getAgentConfig,
      utils.toolkit.getConfig,
      utils.toolkit.listAgentManagement,
    ],
  );
  useWindowEvent("message", handleOauthCallbackMessage);

  useEffect(() => {
    if (formState.type !== "EDIT") {
      return;
    }

    const toolkitConfig = formState.config;
    const rawConfig = toolkitConfig.config;
    const toolSlug = toolkitConfig.toolkit_type;
    let config: Record<string, unknown>;
    if (toolSlug === "shell") {
      config = {
        allowed_domains: Array.isArray(rawConfig.allowed_domains)
          ? getStringArray(rawConfig.allowed_domains)
          : [],
        denied_domains: getStringArray(rawConfig.denied_domains),
      };
    } else if (toolSlug === "mcp") {
      config = {
        server_url: getString(rawConfig.server_url),
        auth_type: getMcpAuthType(rawConfig.auth_type),
        timeout: typeof rawConfig.timeout === "number" ? rawConfig.timeout : 30,
        header_name: getString(rawConfig.header_name),
        token_url: getString(rawConfig.token_url),
        auth_url: getString(rawConfig.auth_url),
        scopes: getStringArray(rawConfig.scopes),
        discovery_url: getString(rawConfig.discovery_url),
      };
    } else if (toolSlug === "github") {
      config = {
        server_url: getString(
          rawConfig.server_url,
          "https://api.githubcopilot.com/mcp/",
        ),
        auth_type:
          rawConfig.auth_type === "bearer" ? rawConfig.auth_type : "bearer",
        github_auth_type: getGithubAuthType(rawConfig.github_auth_type),
        toolsets: Array.isArray(rawConfig.toolsets)
          ? getStringArray(rawConfig.toolsets)
          : ["repos", "issues", "pull_requests", "users"],
        timeout: typeof rawConfig.timeout === "number" ? rawConfig.timeout : 30,
        inject_runtime_environment: Boolean(
          rawConfig.inject_runtime_environment,
        ),
      };
    } else if (toolSlug === "envvar") {
      config = {
        entries: getArray(rawConfig.entries, isRecord).map((entry) => ({
          name: getString(entry.name),
          masked: typeof entry.masked === "boolean" ? entry.masked : true,
        })),
      };
    } else {
      config = rawConfig;
    }

    form.setValues({
      toolkitType: toolSlug,
      slug: toolkitConfig.slug || toolSlug,
      name: toolkitConfig.name,
      description: toolkitConfig.description ?? "",
      prompt: toolkitConfig.prompt ?? "",
      config,
      credentials:
        toolSlug === "mcp"
          ? { type: getMcpAuthType(rawConfig.auth_type) }
          : toolSlug === "github"
            ? { type: getGithubAuthType(rawConfig.github_auth_type) }
            : toolSlug === "envvar"
              ? { values: {} }
              : null,
      enabled: toolkitConfig.enabled,
      alwaysExposeTools: toolkitConfig.always_expose_tools,
    });
    form.resetDirty();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate once after the edit data reaches its terminal state.
  }, [formState.type]);

  const toolOptions = useMemo(
    () =>
      toolkitListState.type === "READY"
        ? toolkitListState.toolkits
            .filter((toolkit) => agentId == null || toolkit.slug !== "shell")
            .map((toolkit) => ({
              value: toolkit.slug,
              label: toolkit.name,
            }))
        : [],
    [agentId, toolkitListState],
  );
  const currentToolSlug = form.getValues().toolkitType;
  const showOauthConnection =
    formState.type === "EDIT" &&
    ["mcp", "notion", "sentry"].includes(currentToolSlug) &&
    (getString(form.getValues().config.auth_type) === "oauth2" ||
      currentToolSlug === "notion" ||
      currentToolSlug === "sentry");
  const onAddScope = useCallback((): void => {
    if (!toolkitId) {
      return;
    }
    createScopeMutation.mutate({ handle, toolkitId });
  }, [createScopeMutation, handle, toolkitId]);
  const onDeleteScope = useCallback(
    (scopeId: string): void => {
      if (!toolkitId) {
        return;
      }
      deleteScopeMutation.mutate({ handle, toolkitId, scopeId });
    },
    [deleteScopeMutation, handle, toolkitId],
  );

  return {
    handle,
    ...(agentId != null && { agentId }),
    embedded,
    toolkitTypeLocked: initialToolkitType != null,
    formState,
    mutationState,
    scopeListState,
    form,
    isEdit: isEditMode,
    backPath,
    toolOptions,
    currentToolSlug,
    showOauthConnection,
    oauthConnectionPending: {
      connect:
        connectOauthMutation.isPending || connectAgentOauthMutation.isPending,
      disconnect:
        disconnectOauthMutation.isPending ||
        disconnectAgentOauthMutation.isPending,
    },
    onSubmit,
    onToolSelect,
    onConfigChange,
    onCredentialsChange,
    onConnectOauth,
    onDisconnectOauth,
    onAddScope,
    onDeleteScope,
    onCancel: () => {
      if (embedded) {
        onComplete?.();
      } else {
        router.push(backPath);
      }
    },
  };
}
