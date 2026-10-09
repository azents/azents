"use client";

/**
 * Toolkit create/update form container hook.
 *
 * Edit mode when toolkitId exists; creates the form state, performs API work,
 * and owns the behavioral callbacks consumed by the ToolkitForm view.
 */

import { useForm, type UseFormReturnType } from "@mantine/form";
import { useWindowEvent } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import {
  type FormEventHandler,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { normalizeCredentialEdits } from "@/shared/lib/redacted-credentials";
import {
  resolveDefaultToolkitSlug,
  trimToolkitWhitespace,
} from "@/shared/lib/toolkit-identifiers";
import { isRecord } from "@/shared/lib/unknown-value";
import { trpc } from "@/trpc/client";
import {
  missingNewGitHubUserRegistration,
  normalizeGitHubUserCredentialEdits,
} from "../github-user-credentials";
import { isGitHubUserMode } from "../github-user-oauth-state";
import { toolkitFormSchema } from "../schemas";
import {
  hydrateToolkitConfig,
  projectToolkitConfig,
  toolkitProjectionUsesOauth,
} from "../toolkit-config-projection";
import { useGitHubUserCreationContainer } from "./useGitHubUserCreationContainer";
import type { GitHubUserSetupState } from "../github-user-oauth-state";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitConfigProjection } from "../toolkit-config-projection";
import type {
  MutationState,
  ToolkitConfigFormState,
  ToolkitListState,
} from "../types";

export interface ToolkitFormContainerProps {
  handle: string;
  toolkitId?: string;
  agentId?: string;
  embedded?: boolean;
  onComplete?: () => void;
  onPendingChange?: (pending: boolean) => void;
  initialToolkitType?: string;
}

export interface ToolkitFormContainerOutput {
  githubCreation: {
    state: GitHubUserSetupState;
    onCancel: () => void;
    onConfirm: () => void;
  };
  configProjection: ToolkitConfigProjection;
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
  onUserSetupPendingChange: (pending: boolean) => void;
  onToolSelect: (toolSlug: string | null) => void;
  onConfigChange: (config: Record<string, unknown>) => void;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  onConnectOauth: () => void;
  onDisconnectOauth: () => void;
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
  brave_search: {
    country: "US",
    search_lang: "en",
    safesearch: "strict",
    timeout: 10,
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
  brave_search: null,
  github: { type: "pat" },
  kubernetes: { clusters: {} },
  envvar: { values: {} },
};

export function useToolkitFormContainer(
  props: ToolkitFormContainerProps,
): ToolkitFormContainerOutput {
  const {
    handle,
    toolkitId,
    agentId,
    embedded = false,
    onComplete,
    onPendingChange,
    initialToolkitType,
  } = props;
  const router = useRouter();
  const t = useTranslations("workspace.toolkits");
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
      slug: "",
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
  const creation = useGitHubUserCreationContainer({
    handle,
    agentId,
    enabled: !isEditMode,
    onComplete,
    onPendingChange,
    onReview: (review) => {
      const hydrated = hydrateToolkitConfig("github", review.config);
      form.setValues({
        toolkitType: "github",
        name: review.name,
        slug: review.slug,
        description: review.description ?? "",
        prompt: review.prompt ?? "",
        config: hydrated.config,
        credentials: hydrated.credentials,
        enabled: review.enabled,
        alwaysExposeTools: review.always_expose_tools,
      });
    },
  });
  useEffect(() => {
    onPendingChange?.(mutationState.type === "SUBMITTING");
  }, [mutationState.type, onPendingChange]);

  const definitionsQuery = trpc.toolkit.listToolkits.useQuery();
  const workspaceToolkitQuery = trpc.toolkit.getConfig.useQuery(
    { handle, toolkitId: toolkitId ?? "" },
    { enabled: isEditMode && agentId == null },
  );
  const agentToolkitQuery = trpc.toolkit.getAgentConfig.useQuery(
    { handle, agentId: agentId ?? "", toolkitConfigId: toolkitId ?? "" },
    { enabled: isEditMode && agentId != null },
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
      form.getValues().description
    ) {
      return;
    }
    const definition = toolkitListState.toolkits.find(
      (toolkit) => toolkit.slug === initialToolkitType,
    );
    if (definition) {
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

  const createMutation = trpc.toolkit.createConfig.useMutation({
    onSuccess: (data) => {
      form.setValues({ name: data.name, slug: data.slug });
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
    onSuccess: async (data) => {
      form.setValues({ name: data.name, slug: data.slug });
      setMutationState({ type: "IDLE", error: null });
      onComplete?.();
      if (agentId) {
        // A committed create must not become an unsaved form after a read failure.
        await utils.toolkit.listAgentManagement
          .invalidate({ handle, agentId })
          .catch(() => null);
        await utils.toolkit.listAgentManagement
          .fetch({ handle, agentId })
          .catch(() => null);
      }
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const updateAgentMutation = trpc.toolkit.updateAgentConfig.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE", error: null });
      onComplete?.();
      const invalidations: Array<Promise<unknown>> = [];
      if (agentId) {
        invalidations.push(
          utils.toolkit.listAgentManagement.invalidate({ handle, agentId }),
        );
      }
      if (agentId && toolkitId) {
        invalidations.push(
          utils.toolkit.getAgentConfig.invalidate({
            handle,
            agentId,
            toolkitConfigId: toolkitId,
          }),
        );
      }
      await Promise.allSettled(invalidations);
      if (agentId) {
        await utils.toolkit.listAgentManagement
          .fetch({ handle, agentId })
          .catch(() => null);
      }
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
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
      const credentials =
        values.toolkitType === "github"
          ? normalizeGitHubUserCredentialEdits(values.credentials ?? null)
          : normalizeCredentialEdits(values.credentials ?? null);
      if (
        values.toolkitType === "github" &&
        values.config.github_auth_type === "github_app_user" &&
        !(
          formState.type === "EDIT" &&
          formState.config.has_credentials &&
          formState.config.config.github_auth_type === "github_app_user"
        ) &&
        missingNewGitHubUserRegistration(credentials).length > 0
      ) {
        setMutationState({
          type: "IDLE",
          error: t("github.registrationRequired"),
        });
        return;
      }

      if (
        !isEditMode &&
        values.toolkitType === "github" &&
        isGitHubUserMode(values.config.github_auth_type)
      ) {
        setMutationState({ type: "IDLE", error: null });
        creation.start(values, credentials);
        return;
      }

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
          ...(trimToolkitWhitespace(values.slug) && { slug: values.slug }),
          ...(trimToolkitWhitespace(values.name) && { name: values.name }),
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
        ...(trimToolkitWhitespace(values.slug) && { slug: values.slug }),
        ...(trimToolkitWhitespace(values.name) && { name: values.name }),
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
      creation,
      formState,
      handle,
      isEditMode,
      t,
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

      if (toolkitListState.type === "READY" && !form.getValues().description) {
        const definition = toolkitListState.toolkits.find(
          (toolkit) => toolkit.slug === toolSlug,
        );
        if (definition) {
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
    const toolSlug = toolkitConfig.toolkit_type;
    const hydrated = hydrateToolkitConfig(toolSlug, toolkitConfig.config);

    form.setValues({
      toolkitType: toolSlug,
      slug: toolkitConfig.slug || toolSlug,
      name: toolkitConfig.name,
      description: toolkitConfig.description ?? "",
      prompt: toolkitConfig.prompt ?? "",
      config: hydrated.config,
      credentials: hydrated.credentials,
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
  const currentDefinition =
    toolkitListState.type === "READY"
      ? (toolkitListState.toolkits.find(
          (toolkit) => toolkit.slug === currentToolSlug,
        ) ?? null)
      : null;
  const canonicalName = currentDefinition?.name ?? "";
  const namePlaceholder = currentToolSlug === "mcp" ? "" : canonicalName;
  const slugPlaceholder = canonicalName
    ? resolveDefaultToolkitSlug(
        trimToolkitWhitespace(form.getValues().name) || canonicalName,
        canonicalName,
      )
    : "";
  const configProjection = projectToolkitConfig(
    currentToolSlug,
    form.getValues().config,
  );
  const showOauthConnection =
    formState.type === "EDIT" && toolkitProjectionUsesOauth(configProjection);

  return {
    githubCreation: {
      state: creation.state,
      onCancel: creation.cancel,
      onConfirm: creation.confirm,
    },
    configProjection,
    handle,
    ...(agentId != null && { agentId }),
    embedded,
    toolkitTypeLocked: initialToolkitType != null,
    formState,
    mutationState,
    form,
    isEdit: isEditMode,
    backPath,
    toolOptions,
    currentToolSlug,
    namePlaceholder,
    slugPlaceholder,
    nameRequired: currentToolSlug === "mcp",
    showOauthConnection,
    oauthConnectionPending: {
      connect:
        connectOauthMutation.isPending || connectAgentOauthMutation.isPending,
      disconnect:
        disconnectOauthMutation.isPending ||
        disconnectAgentOauthMutation.isPending,
    },
    onSubmit,
    onUserSetupPendingChange: props.onPendingChange ?? (() => {}),
    onToolSelect,
    onConfigChange,
    onCredentialsChange,
    onConnectOauth,
    onDisconnectOauth,
    onCancel: () => {
      if (mutationState.type === "SUBMITTING") {
        return;
      }
      if (embedded) {
        onComplete?.();
      } else {
        router.push(backPath);
      }
    },
  };
}
