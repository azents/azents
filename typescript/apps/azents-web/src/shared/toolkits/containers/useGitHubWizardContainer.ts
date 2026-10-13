"use client";

import {
  readSessionStorageValue,
  useInterval,
  useSessionStorage,
  useWindowEvent,
} from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { trimToolkitWhitespace } from "@/shared/lib/toolkit-identifiers";
import { isRecord } from "@/shared/lib/unknown-value";
import { trpc } from "@/trpc/client";
import {
  creationReturnPath,
  deserializeGitHubUserCreation,
  GITHUB_USER_CREATION_KEY,
} from "../github-user-creation-state";
import {
  acceptGitHubCreationResult,
  GitHubWizardOperations,
} from "../github-wizard-operations";
import {
  DEFAULT_GITHUB_WIZARD_SETTINGS,
  finalWizardSettings,
  isWizardMode,
  wizardCandidateRequiresRestart,
  wizardIdentity,
} from "../github-wizard-state";
import type { GitHubWizardProps } from "../components/GitHubWizard";
import type { GitHubUserCreationContext } from "../github-user-creation-state";
import type {
  GitHubWizardAppState,
  GitHubWizardConnection,
  GitHubWizardCredentials,
  GitHubWizardIdentity,
  GitHubWizardMode,
  GitHubWizardPublication,
  GitHubWizardSettings,
} from "../github-wizard-state";
import type { GitHubUserCreationReview } from "@azents/public-client";

export interface GitHubWizardContainerProps {
  handle: string;
  agentId?: string;
  embedded?: boolean;
  initialDescription?: string;
  onComplete?: () => void;
  onPendingChange?: (pending: boolean) => void;
  onAbandonReady?: (abandon: (() => void) | null) => void;
}
const EMPTY_CREDENTIALS: GitHubWizardCredentials = {
  token: "",
  appId: "",
  privateKey: "",
  clientId: "",
  clientSecret: "",
  installationIds: [],
};
function restoredSettings(
  review: GitHubUserCreationReview,
): GitHubWizardSettings {
  return {
    name: review.name,
    slug: review.slug,
    description: review.description ?? "",
    prompt: review.prompt ?? "",
    enabled: review.enabled,
    alwaysExposeTools: review.always_expose_tools,
    toolsets: Array.isArray(review.config.toolsets)
      ? review.config.toolsets.filter(
          (item): item is string => typeof item === "string",
        )
      : DEFAULT_GITHUB_WIZARD_SETTINGS.toolsets,
    timeout:
      typeof review.config.timeout === "number" ? review.config.timeout : 30,
    injectRuntimeEnvironment: review.config.inject_runtime_environment === true,
    runtimeRiskAcknowledged: false,
  };
}

export function useGitHubWizardContainer({
  handle,
  agentId,
  embedded = false,
  initialDescription = "",
  onComplete,
  onPendingChange,
  onAbandonReady,
}: GitHubWizardContainerProps): GitHubWizardProps {
  const t = useTranslations("workspace.toolkits.github.wizard");
  const router = useRouter();
  const utils = trpc.useUtils();
  const scope = { handle, agentId };
  const availability = trpc.toolkit.githubUser.availability.useQuery(scope, {
    retry: false,
  });
  const verifyMutation = trpc.toolkit.githubSetup.verify.useMutation();
  const connectMutation = trpc.toolkit.githubUserCreation.connect.useMutation();
  const cancelMutation = trpc.toolkit.githubUserCreation.cancel.useMutation();
  const confirmMutation = trpc.toolkit.githubUserCreation.confirm.useMutation();
  const createMutation = trpc.toolkit.createConfig.useMutation();
  const createAgentMutation = trpc.toolkit.createAgentConfig.useMutation();
  const installationsMutation =
    trpc.toolkit.getGithubInstallations.useMutation();
  const [, saveContext, clearContext] =
    useSessionStorage<GitHubUserCreationContext | null>({
      key: GITHUB_USER_CREATION_KEY,
      defaultValue: null,
      deserialize: deserializeGitHubUserCreation,
    });
  const [selection, setSelection] = useState<
    | { type: "EMPTY" }
    | { type: "IDENTITY"; identity: GitHubWizardIdentity }
    | { type: "METHOD"; mode: GitHubWizardMode }
  >({ type: "EMPTY" });
  const [connection, setConnection] = useState<GitHubWizardConnection>({
    type: "INPUT",
  });
  const [platformApp, setPlatformApp] = useState<GitHubWizardAppState>({
    type: "LOADING",
  });
  const [settings, setSettings] = useState<GitHubWizardSettings>({
    ...DEFAULT_GITHUB_WIZARD_SETTINGS,
    description: initialDescription,
  });
  const [credentials, setCredentials] =
    useState<GitHubWizardCredentials>(EMPTY_CREDENTIALS);
  const [stage, setStage] = useState<
    "CONNECTION" | "FEATURES" | "RUNTIME" | "REVIEW"
  >("CONNECTION");
  const [publication, setPublication] = useState<GitHubWizardPublication>({
    type: "IDLE",
  });
  const [installationState, setInstallationState] = useState<
    GitHubWizardProps["installationState"]
  >({ type: "IDLE" });
  const epoch = useRef(new GitHubWizardOperations());
  const metadataEpoch = useRef(new GitHubWizardOperations());
  const attempt = useRef<string | null>(null);
  const pending = useRef(false);
  const closed = useRef(false);
  const resumed = useRef(false);
  const restoredReview = useRef(false);
  const descriptionDefaultInitialized = useRef(initialDescription !== "");
  const popup = useRef<Window | null>(null);
  const popupPurpose = useRef<"AUTHORIZE" | "INSTALL">("AUTHORIZE");
  const popupEpoch = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const mode = selection.type === "METHOD" ? selection.mode : null;
  const identity =
    selection.type === "EMPTY"
      ? null
      : selection.type === "IDENTITY"
        ? selection.identity
        : wizardIdentity(selection.mode);
  const returnPath = creationReturnPath(handle, agentId);
  const { start: startPopupWatch, stop: stopPopupWatch } = useInterval(() => {
    if (popup.current?.closed) {
      popup.current = null;
      stopPopupWatch();
      if (!epoch.current.isCurrent(popupEpoch.current)) {
        return;
      }
      if (popupPurpose.current === "INSTALL") {
        void connectInstallations();
      } else {
        setInstallationState({ type: "IDLE" });
      }
    }
  }, 500);
  useEffect(() => () => stopPopupWatch(), [stopPopupWatch]);

  const cancelExact = useCallback(
    (attemptId: string): void => {
      void cancelMutation
        .mutateAsync({ handle, agentId, attemptId })
        .catch(() => null);
    },
    [agentId, cancelMutation, handle],
  );
  const abandon = useCallback((): void => {
    if (pending.current) {
      return;
    }
    epoch.current.next();
    popup.current?.close();
    stopPopupWatch();
    popup.current = null;
    const id = attempt.current;
    attempt.current = null;
    if (id != null) {
      cancelExact(id);
    }
    clearContext();
    setCredentials(EMPTY_CREDENTIALS);
    setConnection({ type: "INPUT" });
    setInstallationState({ type: "IDLE" });
    setStage("CONNECTION");
    setPublication({ type: "IDLE" });
    setSettings((current) => ({ ...current, runtimeRiskAcknowledged: false }));
  }, [cancelExact, clearContext, stopPopupWatch]);
  useEffect(() => {
    onAbandonReady?.(abandon);
    return () => onAbandonReady?.(null);
  }, [abandon, onAbandonReady]);
  useEffect(() => {
    onPendingChange?.(publication.type === "PENDING");
    return () => onPendingChange?.(false);
  }, [onPendingChange, publication.type]);
  useEffect(() => {
    closed.current = false;
    return () => {
      closed.current = true;
    };
  }, []);
  useEffect(() => {
    if (identity != null) {
      headingRef.current?.focus();
    }
  }, [identity, mode, stage]);

  async function loadPlatformApp(): Promise<void> {
    const operation = metadataEpoch.current.next();
    setPlatformApp({ type: "LOADING" });
    try {
      const result = await utils.toolkit.githubSetup.app.fetch(scope, {
        retry: false,
        staleTime: 0,
      });
      if (!metadataEpoch.current.isCurrent(operation) || closed.current) {
        return;
      }
      setPlatformApp(
        result.app == null
          ? { type: "ERROR", message: t("metadataError") }
          : { type: "READY", app: result.app },
      );
    } catch {
      if (metadataEpoch.current.isCurrent(operation) && !closed.current) {
        setPlatformApp({ type: "ERROR", message: t("metadataError") });
      }
    }
  }
  useEffect(() => {
    if (
      availability.data?.platform_modes.user_account === "configured" ||
      availability.data?.platform_modes.installation === "configured"
    ) {
      void loadPlatformApp();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetch once per current registration availability, not on every local edit.
  }, [
    availability.data?.platform_modes.user_account,
    availability.data?.platform_modes.installation,
  ]);

  async function loadCandidateApp(
    candidate: NonNullable<GitHubWizardProps["candidate"]>,
    operation: number,
  ): Promise<void> {
    try {
      const result = await utils.toolkit.githubUserCreation.app.fetch(
        {
          ...scope,
          attemptId: candidate.attempt_id,
        },
        { retry: false, staleTime: 0 },
      );
      if (!epoch.current.isCurrent(operation) || closed.current) {
        return;
      }
      setConnection({
        type: "CANDIDATE",
        candidate,
        app:
          result.app == null
            ? { type: "ERROR", message: t("metadataError") }
            : { type: "READY", app: result.app },
      });
    } catch (error: unknown) {
      if (epoch.current.isCurrent(operation) && !closed.current) {
        setConnection(
          wizardCandidateRequiresRestart(error)
            ? { type: "ERROR", message: t("restart") }
            : {
                type: "CANDIDATE",
                candidate,
                app: { type: "ERROR", message: t("metadataError") },
              },
        );
      }
    }
  }
  useEffect(() => {
    if (resumed.current) {
      return;
    }
    resumed.current = true;
    const saved = readSessionStorageValue<GitHubUserCreationContext | null>({
      key: GITHUB_USER_CREATION_KEY,
      deserialize: deserializeGitHubUserCreation,
    });
    if (
      saved == null ||
      saved.handle !== handle ||
      saved.agentId !== agentId ||
      saved.returnPath !== returnPath
    ) {
      return;
    }
    restoredReview.current = true;
    attempt.current = saved.attemptId;
    if (saved.phase !== "REVIEW") {
      setConnection({ type: "ERROR", message: t("restart") });
      return;
    }
    const operation = epoch.current.next();
    setConnection({ type: "LOADING" });
    void utils.toolkit.githubUserCreation.review
      .fetch({ ...scope, attemptId: saved.attemptId })
      .then((review) => {
        if (!epoch.current.isCurrent(operation) || closed.current) {
          return;
        }
        const restoredMode = review.config.github_auth_type;
        if (!isWizardMode(restoredMode)) {
          setConnection({ type: "ERROR", message: t("restart") });
          return;
        }
        setSelection({ type: "METHOD", mode: restoredMode });
        setSettings(restoredSettings(review));
        setCredentials(EMPTY_CREDENTIALS);
        setConnection({
          type: "CANDIDATE",
          candidate: review.candidate,
          app: { type: "LOADING" },
        });
        void loadCandidateApp(review.candidate, operation);
      })
      .catch(() => {
        if (epoch.current.isCurrent(operation) && !closed.current) {
          setConnection({ type: "ERROR", message: t("restart") });
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resume only the exact entry context once; do not overwrite downstream edits on refresh.
  }, [agentId, handle, returnPath]);

  useEffect(() => {
    if (
      restoredReview.current ||
      descriptionDefaultInitialized.current ||
      initialDescription === ""
    ) {
      return;
    }
    descriptionDefaultInitialized.current = true;
    setSettings((current) => ({ ...current, description: initialDescription }));
  }, [initialDescription]);

  function config(): Record<string, unknown> {
    return {
      server_url: "https://api.githubcopilot.com/mcp/",
      auth_type: "bearer",
      github_auth_type: mode,
      toolsets: settings.toolsets,
      timeout: settings.timeout,
      inject_runtime_environment: settings.injectRuntimeEnvironment,
    };
  }
  function credentialPayload(): Record<string, unknown> {
    if (mode === "pat") {
      return { type: mode, token: credentials.token };
    }
    if (mode === "github_app_platform_user") {
      return { type: mode };
    }
    if (mode === "github_app_user") {
      return {
        type: mode,
        app_id: credentials.appId,
        private_key: credentials.privateKey,
        client_id: credentials.clientId,
        client_secret: credentials.clientSecret,
      };
    }
    if (connection.type !== "VERIFIED") {
      return { type: mode };
    }
    const targets = connection.verification.installations.map((target) => ({
      installation_id: target.installation_id,
      account_login: target.account_login,
      account_type: target.account_type,
      account_avatar_url: target.account_avatar_url,
    }));
    return mode === "github_app"
      ? {
          type: mode,
          app_id: credentials.appId,
          private_key: credentials.privateKey,
          installations: targets,
        }
      : { type: mode, installations: targets };
  }
  async function connect(): Promise<void> {
    if (
      mode == null ||
      pending.current ||
      connection.type === "LOADING" ||
      (connection.type === "VERIFIED" && connection.transport === "CHECKING")
    ) {
      return;
    }
    const operation = epoch.current.next();
    setConnection(
      connection.type === "VERIFIED"
        ? { ...connection, transport: "CHECKING" }
        : { type: "LOADING" },
    );
    setPublication({ type: "IDLE" });
    try {
      if (mode === "github_app_user" || mode === "github_app_platform_user") {
        const result = await connectMutation.mutateAsync({
          ...scope,
          toolkitType: "github",
          ...(trimToolkitWhitespace(settings.name) && { name: settings.name }),
          ...(trimToolkitWhitespace(settings.slug) && { slug: settings.slug }),
          description: settings.description || null,
          prompt: settings.prompt || null,
          enabled: settings.enabled,
          alwaysExposeTools: settings.alwaysExposeTools,
          config: config(),
          credentials: credentialPayload(),
        });
        if (
          !acceptGitHubCreationResult(
            epoch.current.isCurrent(operation) && !closed.current,
            result.attempt_id,
            cancelExact,
          )
        ) {
          return;
        }
        attempt.current = result.attempt_id;
        saveContext({
          ...scope,
          attemptId: result.attempt_id,
          returnPath,
          phase: "AUTHORIZING",
        });
        // Intentional same-context navigation keeps the encrypted attempt alive for callback resume.
        window.location.assign(result.authorization_url);
        return;
      }
      const transport = {
        toolsets: settings.toolsets,
        timeout: settings.timeout,
      };
      const verification =
        mode === "pat"
          ? { github_auth_type: mode, token: credentials.token, transport }
          : mode === "github_app"
            ? {
                github_auth_type: mode,
                app_id: credentials.appId,
                private_key: credentials.privateKey,
                installation_ids: credentials.installationIds,
                transport,
              }
            : {
                github_auth_type: mode,
                installation_ids: credentials.installationIds,
                transport,
              };
      const result = await verifyMutation.mutateAsync({
        ...scope,
        verification,
      });
      if (!epoch.current.isCurrent(operation) || closed.current) {
        return;
      }
      setConnection({
        type: "VERIFIED",
        verification: result,
        transport: "CURRENT",
      });
    } catch {
      if (epoch.current.isCurrent(operation) && !closed.current) {
        setConnection(
          connection.type === "VERIFIED"
            ? { ...connection, transport: "ERROR" }
            : { type: "ERROR", message: t("connectionError") },
        );
      }
    }
  }
  function openPopup(
    url: string,
    operation: number,
    purpose: "AUTHORIZE" | "INSTALL",
  ): void {
    if (!epoch.current.isCurrent(operation) || closed.current) {
      return;
    }
    popup.current?.close();
    popupEpoch.current = operation;
    popupPurpose.current = purpose;
    popup.current = window.open(
      url,
      "github-installation-popup",
      "width=1024,height=768",
    );
    if (popup.current == null) {
      setInstallationState({ type: "ERROR" });
    } else {
      startPopupWatch();
    }
  }
  async function connectInstallations(): Promise<void> {
    const operation = epoch.current.next();
    setInstallationState({ type: "LOADING" });
    try {
      const result = await utils.toolkit.getGithubOauthUrl.fetch(scope);
      openPopup(result.oauth_url, operation, "AUTHORIZE");
    } catch {
      if (epoch.current.isCurrent(operation) && !closed.current) {
        setInstallationState({ type: "ERROR" });
      }
    }
  }
  useWindowEvent("message", (event: MessageEvent<unknown>): void => {
    const operation = popupEpoch.current;
    if (
      !epoch.current.isCurrent(operation) ||
      popup.current == null ||
      event.source !== popup.current ||
      event.origin !== window.location.origin ||
      !isRecord(event.data)
    ) {
      return;
    }
    if (event.data.type === "azents-github-app-installed") {
      stopPopupWatch();
      popup.current = null;
      void connectInstallations();
      return;
    }
    if (
      event.data.type !== "azents-github-installations-code" ||
      typeof event.data.code !== "string" ||
      typeof event.data.state !== "string"
    ) {
      return;
    }
    popup.current = null;
    stopPopupWatch();
    void installationsMutation
      .mutateAsync({ ...scope, code: event.data.code, state: event.data.state })
      .then((result) => {
        if (!epoch.current.isCurrent(operation) || closed.current) {
          return;
        }
        setInstallationState({
          type: "READY",
          installations: result.installations,
        });
      })
      .catch(() => {
        if (epoch.current.isCurrent(operation) && !closed.current) {
          setInstallationState({ type: "ERROR" });
        }
      });
  });
  const ready =
    connection.type === "CANDIDATE"
      ? connection.app.type === "READY"
      : connection.type === "VERIFIED" &&
        connection.transport === "CURRENT" &&
        connection.verification.connectivity.status === "ready" &&
        connection.verification.installations.every(
          (target) => target.status === "ready",
        );
  async function publish(): Promise<void> {
    if (
      !ready ||
      mode == null ||
      pending.current ||
      publication.type === "SUCCESS" ||
      publication.type === "UNCERTAIN" ||
      (settings.injectRuntimeEnvironment && !settings.runtimeRiskAcknowledged)
    ) {
      return;
    }
    pending.current = true;
    onPendingChange?.(true);
    let toolkitId: string;
    setPublication({ type: "PENDING" });
    try {
      if (connection.type === "CANDIDATE") {
        const result = await confirmMutation.mutateAsync({
          ...scope,
          attemptId: connection.candidate.attempt_id,
          settings: finalWizardSettings(settings),
        });
        toolkitId = result.toolkit_id;
      } else {
        const input = {
          handle,
          toolkitType: "github",
          ...(trimToolkitWhitespace(settings.name) && { name: settings.name }),
          ...(trimToolkitWhitespace(settings.slug) && { slug: settings.slug }),
          description: settings.description,
          prompt: settings.prompt,
          config: config(),
          credentials: credentialPayload(),
          enabled: settings.enabled,
          alwaysExposeTools: settings.alwaysExposeTools,
        };
        const result =
          agentId == null
            ? await createMutation.mutateAsync(input)
            : await createAgentMutation.mutateAsync({ ...input, agentId });
        toolkitId = result.id;
      }
    } catch (error: unknown) {
      const code =
        isRecord(error) && isRecord(error.data) ? error.data.code : null;
      if (
        code === "BAD_REQUEST" ||
        code === "CONFLICT" ||
        code === "FORBIDDEN" ||
        code === "NOT_FOUND" ||
        code === "UNAUTHORIZED"
      ) {
        setPublication({ type: "ERROR", message: t("saveError") });
      } else {
        setPublication({ type: "UNCERTAIN" });
      }
      return;
    } finally {
      pending.current = false;
    }
    // Publication is already committed; subsequent read failures cannot reopen this form.
    attempt.current = null;
    clearContext();
    setCredentials(EMPTY_CREDENTIALS);
    setPublication({ type: "SUCCESS" });
    onComplete?.();
    void Promise.allSettled([
      utils.toolkit.listConfigs.invalidate({ handle }),
      utils.toolkit.listAvailableConfigs.invalidate({ handle }),
      utils.toolkit.listAgentManagement.invalidate(),
    ]);
    if (!embedded) {
      router.replace(
        agentId == null
          ? `/w/${handle}/toolkits/${toolkitId}/edit`
          : returnPath,
      );
    }
  }
  return {
    embedded,
    sharingScope: agentId == null ? "workspace_shared" : "agent_only",
    identity,
    mode,
    connection,
    platformApp,
    credentials,
    settings,
    stage,
    publication,
    installationState,
    headingRef,
    candidate: connection.type === "CANDIDATE" ? connection.candidate : null,
    availability: availability.isError
      ? { type: "ERROR" }
      : availability.data
        ? {
            type: "READY",
            userAccount: availability.data.platform_modes.user_account,
            installation: availability.data.platform_modes.installation,
            callbackUrl: availability.data.callback_url,
          }
        : { type: "LOADING" },
    canContinue: ready,
    onIdentity: (next) => {
      if (pending.current || identity === next) {
        return;
      }
      abandon();
      setSelection({ type: "IDENTITY", identity: next });
    },
    onMode: (next) => {
      if (pending.current || mode === next) {
        return;
      }
      abandon();
      setSelection({ type: "METHOD", mode: next });
    },
    onCredentials: (next) => {
      if (pending.current) {
        return;
      }
      epoch.current.next();
      setCredentials(next);
      setSettings((current) => ({
        ...current,
        runtimeRiskAcknowledged: false,
      }));
      setConnection({ type: "INPUT" });
      setStage("CONNECTION");
    },
    onSettings: (next) => {
      if (next.description !== settings.description) {
        descriptionDefaultInitialized.current = true;
      }
      if (pending.current || publication.type === "UNCERTAIN") {
        return;
      }
      if (
        connection.type === "VERIFIED" &&
        (next.timeout !== settings.timeout ||
          next.toolsets.join("\0") !== settings.toolsets.join("\0"))
      ) {
        epoch.current.next();
        setConnection({ ...connection, transport: "STALE" });
      }
      setSettings(next);
    },
    onConnect: () => {
      void connect();
    },
    onRetryMetadata: () => {
      if (connection.type === "CANDIDATE") {
        setConnection({ ...connection, app: { type: "LOADING" } });
        void loadCandidateApp(connection.candidate, epoch.current.next());
      } else {
        void loadPlatformApp();
      }
    },
    onRetryPlatformMetadata: () => {
      void loadPlatformApp();
    },
    onRetryAvailability: () => {
      void utils.toolkit.githubUser.availability.invalidate(scope);
    },
    onContinue: () => {
      if (!ready || pending.current) {
        return;
      }
      setStage(
        stage === "CONNECTION"
          ? "FEATURES"
          : stage === "FEATURES"
            ? "RUNTIME"
            : "REVIEW",
      );
    },
    onReset: () => {
      if (pending.current) {
        return;
      }
      abandon();
    },
    onClose: () => {
      if (pending.current) {
        return;
      }
      abandon();
      if (embedded) {
        onComplete?.();
      } else {
        router.push(agentId == null ? `/w/${handle}/toolkits` : returnPath);
      }
    },
    onInspect: () => {
      if (embedded) {
        onComplete?.();
      } else {
        router.push(agentId == null ? `/w/${handle}/toolkits` : returnPath);
      }
    },
    onPublish: () => {
      void publish();
    },
    onConnectInstallations: () => {
      void connectInstallations();
    },
    onInstallApp: () => {
      const operation = epoch.current.next();
      void utils.toolkit.getGithubInstallUrl
        .fetch(scope)
        .then((result) => openPopup(result.install_url, operation, "INSTALL"))
        .catch(() => {
          if (epoch.current.isCurrent(operation) && !closed.current) {
            setInstallationState({ type: "ERROR" });
          }
        });
    },
  };
}
