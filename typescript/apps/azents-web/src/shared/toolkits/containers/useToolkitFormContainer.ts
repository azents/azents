"use client";

/** Common Provider form state; owner-specific I/O is bound by the narrow adapter. */
import { useForm } from "@mantine/form";
import { readSessionStorageValue, useWindowEvent } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { normalizeCredentialEdits } from "@/shared/lib/redacted-credentials";
import {
  resolveDefaultToolkitSlug,
  trimToolkitWhitespace,
} from "@/shared/lib/toolkit-identifiers";
import { trpc } from "@/trpc/client";
import {
  deserializeGitHubUserCreation,
  GITHUB_USER_CREATION_KEY,
  gitHubCreationMatches,
} from "../github-user-creation-state";
import {
  missingNewGitHubUserRegistration,
  normalizeGitHubUserCredentialEdits,
} from "../github-user-credentials";
import {
  deserializeGoogleResume,
  GOOGLE_RESUME_KEY,
  googleResumeMatches,
} from "../google-resume";
import { decodeOAuthCallbackMessage } from "../popup-messages";
import {
  projectGitHubAuthEvidence,
  projectGitHubFormRegistration,
} from "../provider-config-views";
import { toolkitFormSchema } from "../schemas";
import {
  hydrateToolkitConfig,
  projectToolkitConfig,
  toolkitProjectionUsesOauth,
} from "../toolkit-config-projection";
import { usesToolkitCreationWizard } from "../toolkit-form-lifecycle";
import { useToolkitOwnerAdapter } from "./useToolkitOwnerAdapter";
import type { ToolkitFormProps } from "../components/ToolkitForm";
import type { GitHubUserCreationContext } from "../github-user-creation-state";
import type { GoogleResume } from "../google-resume";
import type { ToolkitFormValues } from "../schemas";
import type {
  PersonalToolkitOrigin,
  ToolkitOwnerScope,
} from "../toolkit-owner-scope";
import type { MutationState, ToolkitListState } from "../types";
import type { ToolkitSavedMetadata } from "./useToolkitOwnerAdapter";
import type { FormEventHandler } from "react";

export type ToolkitFormContainerProps = ToolkitOwnerScope & {
  navigationOrigin?: PersonalToolkitOrigin;
  toolkitId?: string;
  embedded?: boolean;
  onComplete?: () => void;
  onPendingChange?: (pending: boolean) => void;
  onAbandonReady?: (abandon: (() => void) | null) => void;
  initialToolkitType?: string;
};
export type ToolkitFormContainerOutput = ToolkitFormProps;

const DEFAULT_CONFIGS: Record<string, Record<string, unknown>> = {
  shell: { allowed_domains: [], denied_domains: [] },
  mcp: { server_url: "", auth_type: "none", timeout: 30 },
  gcp: {
    project_id: "",
    services: ["logging", "monitoring"],
    writable_services: [],
    timeout: 30,
  },
  aws: { region: "us-east-1", role_arn: null, external_id: null, timeout: 30 },
  google_analytics: { default_property_id: null, timeout: 30 },
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
};
const DEFAULT_CREDENTIALS: Record<string, Record<string, unknown> | null> = {
  shell: null,
  mcp: { type: "none" },
  gcp: { service_account_key: {} },
  aws: { access_key_id: "", secret_access_key: "" },
  google_analytics: { service_account_key: {} },
  brave_search: null,
  github: { type: "pat" },
  kubernetes: { clusters: {} },
};

export function useToolkitFormContainer(
  props: ToolkitFormContainerProps,
): ToolkitFormContainerOutput {
  const {
    toolkitId,
    embedded = false,
    onComplete,
    onPendingChange,
    initialToolkitType,
  } = props;
  const handle = props.handle;
  const agentId = "agentId" in props ? props.agentId : null;
  const personalOwner = "owner" in props;
  const scope = useMemo<ToolkitOwnerScope>(
    () =>
      personalOwner
        ? { owner: "user", handle }
        : { handle, ...(agentId != null && { agentId }) },
    [personalOwner, handle, agentId],
  );
  const router = useRouter();
  const t = useTranslations("workspace.toolkits");
  const setup = useTranslations("toolkitSetup");
  const adapter = useToolkitOwnerAdapter(scope, toolkitId ?? null);
  const formState = adapter.state;
  const isEditMode = toolkitId != null;
  const backPath =
    "owner" in scope
      ? `/w/${encodeURIComponent(handle)}/personal-tools`
      : scope.agentId == null
        ? `/w/${scope.handle}/toolkits`
        : `/w/${scope.handle}/agents/${scope.agentId}/settings/capabilities#agent-toolkits`;
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
  const [providerPending, setProviderPending] = useState(false);
  const [oauthDisconnectConfirmation, setOauthDisconnectConfirmation] =
    useState(false);
  useEffect(() => {
    if (isEditMode) {
      return;
    }
    const saved = readSessionStorageValue<GitHubUserCreationContext | null>({
      key: GITHUB_USER_CREATION_KEY,
      deserialize: deserializeGitHubUserCreation,
    });
    if (saved != null && gitHubCreationMatches(saved, scope)) {
      form.setFieldValue("toolkitType", "github");
    }
    const google = readSessionStorageValue<GoogleResume | null>({
      key: GOOGLE_RESUME_KEY,
      deserialize: deserializeGoogleResume,
    });
    if (google != null && googleResumeMatches(google, scope)) {
      form.setFieldValue("toolkitType", "google");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- restore entry selection only; each Wizard owns exact review hydration.
  }, [agentId, handle, isEditMode]);
  const definitionsQuery = trpc.toolkit.listToolkits.useQuery();
  const toolkitListState: ToolkitListState = useMemo(
    () =>
      definitionsQuery.isLoading
        ? { type: "LOADING" }
        : definitionsQuery.isError
          ? { type: "ERROR" }
          : { type: "READY", toolkits: definitionsQuery.data?.items ?? [] },
    [
      definitionsQuery.data,
      definitionsQuery.isError,
      definitionsQuery.isLoading,
    ],
  );
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
  const operationPending =
    mutationState.type === "SUBMITTING" ||
    providerPending ||
    adapter.saving ||
    adapter.connecting ||
    adapter.disconnecting;
  useEffect(() => {
    onPendingChange?.(operationPending);
  }, [operationPending, onPendingChange]);

  async function submitForm(values: ToolkitFormValues): Promise<void> {
    if (
      operationPending ||
      (!isEditMode && usesToolkitCreationWizard(values.toolkitType))
    ) {
      return;
    }
    const credentials =
      values.toolkitType === "github"
        ? normalizeGitHubUserCredentialEdits(values.credentials ?? null)
        : normalizeCredentialEdits(values.credentials ?? null);
    if (
      values.toolkitType === "github" &&
      projectGitHubAuthEvidence(values.config).byoaUser &&
      !(
        formState.type === "EDIT" &&
        formState.config.has_credentials &&
        projectGitHubAuthEvidence(formState.config.config).byoaUser
      ) &&
      missingNewGitHubUserRegistration(credentials).length > 0
    ) {
      setMutationState({
        type: "IDLE",
        error: t("github.registrationRequired"),
      });
      return;
    }
    setMutationState({ type: "SUBMITTING" });
    let saved: ToolkitSavedMetadata;
    try {
      saved = await adapter.save(values, credentials);
    } catch (error: unknown) {
      setMutationState({
        type: "IDLE",
        error:
          error instanceof Error ? error.message : setup("operationFailed"),
      });
      return;
    }
    form.setValues({ name: saved.name, slug: saved.slug });
    setMutationState({ type: "IDLE", error: null });
    // The save is acknowledged before any optional follow-up read.
    if (embedded || (!("owner" in scope) && scope.agentId != null)) {
      onComplete?.();
    } else {
      router.push(backPath);
    }
    void adapter.invalidate();
  }
  const onSubmit: FormEventHandler<HTMLFormElement> = form.onSubmit(submitForm);
  const onToolSelect = (toolSlug: string | null): void => {
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
  };
  const onConfigChange = (config: Record<string, unknown>): void => {
    form.setFieldValue("config", config);
  };
  const onCredentialsChange = (
    credentials: Record<string, unknown> | null,
  ): void => {
    form.setFieldValue("credentials", credentials);
  };
  async function connectOauth(): Promise<void> {
    if (formState.type !== "EDIT" || operationPending) {
      return;
    }
    try {
      const url = await adapter.connect();
      window.open(url, "mcp-oauth-popup", "width=1024,height=768");
    } catch (error: unknown) {
      setMutationState({
        type: "IDLE",
        error:
          error instanceof Error ? error.message : setup("operationFailed"),
      });
    }
  }
  async function disconnectOauth(): Promise<void> {
    if (formState.type !== "EDIT" || operationPending) {
      return;
    }
    try {
      await adapter.disconnect();
      setOauthDisconnectConfirmation(false);
    } catch (error: unknown) {
      setMutationState({
        type: "IDLE",
        error:
          error instanceof Error ? error.message : setup("operationFailed"),
      });
    }
  }
  const handleOauthCallbackMessage = useCallback(
    (event: MessageEvent<unknown>): void => {
      if (
        event.origin === window.location.origin &&
        formState.type === "EDIT" &&
        decodeOAuthCallbackMessage(event, window.location.origin) != null
      ) {
        void adapter.invalidate();
      }
    },
    [adapter, formState.type],
  );
  useWindowEvent("message", handleOauthCallbackMessage);
  useEffect(() => {
    if (formState.type !== "EDIT") {
      return;
    }
    const saved = formState.config;
    const hydrated = hydrateToolkitConfig(saved.toolkit_type, saved.config);
    form.setValues({
      toolkitType: saved.toolkit_type,
      slug: saved.slug || saved.toolkit_type,
      name: saved.name,
      description: saved.description ?? "",
      prompt: saved.prompt ?? "",
      config: hydrated.config,
      credentials: hydrated.credentials,
      enabled: saved.enabled,
      alwaysExposeTools: saved.always_expose_tools,
    });
    form.resetDirty();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate once after edit data reaches its terminal state; retain unsaved metadata on grant refresh.
  }, [formState.type]);
  const toolOptions = useMemo(
    () =>
      toolkitListState.type === "READY"
        ? toolkitListState.toolkits
            .filter((toolkit) => agentId == null || toolkit.slug !== "shell")
            .map((toolkit) => ({ value: toolkit.slug, label: toolkit.name }))
        : [],
    [agentId, toolkitListState],
  );
  const currentToolSlug = form.getValues().toolkitType;
  const definition =
    toolkitListState.type === "READY"
      ? toolkitListState.toolkits.find(
          (toolkit) => toolkit.slug === currentToolSlug,
        )
      : null;
  const canonicalName = definition?.name ?? "";
  const configProjection = projectToolkitConfig(
    currentToolSlug,
    form.getValues().config,
  );
  return {
    scope,
    githubRegistration: projectGitHubFormRegistration(
      formState.type === "EDIT" ? formState.config.config : null,
      form.getValues().config,
      form.getValues().credentials ?? null,
    ),
    onComplete,
    onAbandonReady: props.onAbandonReady,
    navigationOrigin: props.navigationOrigin,
    configProjection,
    embedded,
    toolkitTypeLocked: initialToolkitType != null,
    formState,
    mutationState,
    operationPending,
    form,
    isEdit: isEditMode,
    backPath,
    toolOptions,
    currentToolSlug,
    namePlaceholder: currentToolSlug === "mcp" ? "" : canonicalName,
    slugPlaceholder: canonicalName
      ? resolveDefaultToolkitSlug(
          trimToolkitWhitespace(form.getValues().name) || canonicalName,
          canonicalName,
        )
      : "",
    nameRequired: currentToolSlug === "mcp",
    showOauthConnection:
      formState.type === "EDIT" && toolkitProjectionUsesOauth(configProjection),
    oauthConnectionPending: {
      connect: adapter.connecting,
      disconnect: adapter.disconnecting,
    },
    onSubmit,
    onUserSetupPendingChange: setProviderPending,
    onToolSelect,
    onConfigChange,
    onCredentialsChange,
    onConnectOauth: () => {
      void connectOauth();
    },
    onDisconnectOauth: () => {
      if (!personalOwner || oauthDisconnectConfirmation) {
        void disconnectOauth();
      }
    },
    oauthDisconnectConfirmation,
    onAskDisconnectOauth: () => {
      if (operationPending) {
        return;
      }
      if (personalOwner) {
        setOauthDisconnectConfirmation(true);
      } else {
        void disconnectOauth();
      }
    },
    onDismissDisconnectOauth: () => {
      if (!operationPending) {
        setOauthDisconnectConfirmation(false);
      }
    },
    onCancel: () => {
      if (operationPending) {
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
