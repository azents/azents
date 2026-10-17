"use client";

import {
  readSessionStorageValue,
  useInterval,
  useSessionStorage,
  useWindowEvent,
} from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trimToolkitWhitespace } from "@/shared/lib/toolkit-identifiers";
import { isRecord } from "@/shared/lib/unknown-value";
import { trpc } from "@/trpc/client";
import {
  creationReturnPath,
  deserializeGitHubUserCreation,
  GITHUB_USER_CREATION_KEY,
  gitHubCreationMatches,
} from "../github-user-creation-state";
import {
  acceptGitHubCreationResult,
  GitHubWizardOperations,
} from "../github-wizard-operations";
import { soleGitHubChoice, soleGitHubMethod } from "../github-wizard-selection";
import {
  DEFAULT_GITHUB_WIZARD_SETTINGS,
  finalWizardSettings,
  gitHubWizardConnectionReady,
  wizardCandidateRequiresRestart,
  wizardIdentity,
} from "../github-wizard-state";
import { decodeGitHubPopupMessage } from "../popup-messages";
import {
  projectGitHubReviewSettings,
  projectGitHubWizardMode,
} from "../provider-config-views";
import { toolkitManagementPath } from "../toolkit-owner-scope";
import { useGitHubWizardProgression } from "./useGitHubWizardProgression";
import type { GitHubWizardProps } from "../components/GitHubWizard";
import type { GitHubUserCreationContext } from "../github-user-creation-state";
import type {
  GitHubWizardAppState,
  GitHubWizardAvailability,
  GitHubWizardConnection,
  GitHubWizardCredentials,
  GitHubWizardIdentity,
  GitHubWizardMode,
  GitHubWizardPublication,
  GitHubWizardSettings,
} from "../github-wizard-state";
import type {
  PersonalToolkitOrigin,
  ToolkitOwnerScope,
} from "../toolkit-owner-scope";
import type { GitHubUserCreationReview } from "@azents/public-client";

export type GitHubWizardContainerProps = ToolkitOwnerScope & {
  navigationOrigin?: PersonalToolkitOrigin;
  embedded?: boolean;
  initialDescription?: string;
  onComplete?: () => void;
  onPendingChange?: (pending: boolean) => void;
  onAbandonReady?: (abandon: (() => void) | null) => void;
};
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
  const config = projectGitHubReviewSettings(review.config);
  return {
    name: review.name,
    slug: review.slug,
    description: review.description ?? "",
    prompt: review.prompt ?? "",
    enabled: review.enabled,
    alwaysExposeTools: review.always_expose_tools,
    toolsets: config.toolsets,
    timeout: config.timeout,
    injectRuntimeEnvironment: config.inject_runtime_environment,
    runtimeRiskAcknowledged: false,
  };
}

export function useGitHubWizardContainer(
  props: GitHubWizardContainerProps,
): GitHubWizardProps {
  const {
    embedded = false,
    initialDescription = "",
    onComplete,
    onPendingChange,
    onAbandonReady,
  } = props;
  const t = useTranslations("workspace.toolkits.github.wizard");
  const router = useRouter();
  const utils = trpc.useUtils();
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
  const availability = trpc.toolkit.githubUser.availability.useQuery(scope, {
    retry: false,
  });
  const verifyMutation = trpc.toolkit.githubSetup.verify.useMutation();
  const connectMutation = trpc.toolkit.githubUserCreation.connect.useMutation();
  const cancelMutation = trpc.toolkit.githubUserCreation.cancel.useMutation();
  const confirmMutation = trpc.toolkit.githubUserCreation.confirm.useMutation();
  const createMutation = trpc.toolkit.createConfig.useMutation();
  const createAgentMutation = trpc.toolkit.createAgentConfig.useMutation();
  const createPersonalMutation = trpc.personalToolkit.create.useMutation();
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
  const progression = useGitHubWizardProgression();
  const installationSelectionTouched = useRef(false);
  const mode = selection.type === "METHOD" ? selection.mode : null;
  const identity =
    selection.type === "EMPTY"
      ? null
      : selection.type === "IDENTITY"
        ? selection.identity
        : wizardIdentity(selection.mode);
  const returnPath = creationReturnPath(scope, props.navigationOrigin);
  const listPath =
    "owner" in scope
      ? `/w/${encodeURIComponent(handle)}/personal-tools`
      : scope.agentId == null
        ? `/w/${scope.handle}/toolkits`
        : returnPath;
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
        .mutateAsync({ ...scope, attemptId })
        .catch(() => null);
    },
    [scope, cancelMutation],
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
    installationSelectionTouched.current = false;
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
  const availabilityState = useMemo<GitHubWizardAvailability>(
    () =>
      availability.isError
        ? { type: "ERROR" }
        : availability.data
          ? {
              type: "READY",
              userAccount: availability.data.platform_modes.user_account,
              installation: availability.data.platform_modes.installation,
              callbackUrl: availability.data.callback_url,
            }
          : { type: "LOADING" },
    [availability.isError, availability.data],
  );
  useEffect(() => {
    const sole = soleGitHubMethod(identity, availabilityState);
    if (selection.type === "IDENTITY" && sole != null) {
      setSelection({ type: "METHOD", mode: sole });
    }
    // Selection may finish when availability arrives; refresh never requests focus or scroll.
  }, [identity, selection.type, availabilityState]);

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
      !gitHubCreationMatches(saved, scope) ||
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
        const restoredMode = projectGitHubWizardMode(review.config);
        if (restoredMode == null) {
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
    const message = decodeGitHubPopupMessage(
      event,
      window.location.origin,
      popup.current,
      epoch.current.isCurrent(operation),
    );
    if (message == null) {
      return;
    }
    if (message.type === "azents-github-app-installed") {
      stopPopupWatch();
      popup.current = null;
      void connectInstallations();
      return;
    }
    popup.current = null;
    stopPopupWatch();
    void installationsMutation
      .mutateAsync({ ...scope, code: message.code, state: message.state })
      .then((result) => {
        if (!epoch.current.isCurrent(operation) || closed.current) {
          return;
        }
        setInstallationState({
          type: "READY",
          installations: result.installations,
        });
        const sole = soleGitHubChoice(
          "READY",
          result.installations.map((item) => String(item.id)),
          installationSelectionTouched.current,
        );
        if (sole != null) {
          setCredentials((current) =>
            current.installationIds.length === 0
              ? { ...current, installationIds: [sole] }
              : current,
          );
        }
      })
      .catch(() => {
        if (epoch.current.isCurrent(operation) && !closed.current) {
          setInstallationState({ type: "ERROR" });
        }
      });
  });
  const ready = gitHubWizardConnectionReady(connection);
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
          "owner" in scope
            ? await createPersonalMutation.mutateAsync({
                ...input,
                handle: scope.handle,
              })
            : scope.agentId == null
              ? await createMutation.mutateAsync({
                  ...input,
                  handle: scope.handle,
                })
              : await createAgentMutation.mutateAsync({
                  ...input,
                  handle: scope.handle,
                  agentId: scope.agentId,
                });
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
    if ("owner" in scope) {
      void Promise.allSettled([
        utils.personalToolkit.list.invalidate({ handle: scope.handle }),
        utils.personalToolkit.get.invalidate({ handle: scope.handle }),
        utils.personalToolkit.accessForAgent.invalidate({
          handle: scope.handle,
        }),
      ]);
    } else {
      void Promise.allSettled([
        utils.toolkit.listConfigs.invalidate({ handle: scope.handle }),
        utils.toolkit.listAvailableConfigs.invalidate({ handle: scope.handle }),
        utils.toolkit.listAgentManagement.invalidate(),
      ]);
    }
    if (!embedded) {
      router.replace(toolkitManagementPath(scope, toolkitId));
    }
  }
  return {
    embedded,
    sharingScope:
      "owner" in scope
        ? "personal"
        : scope.agentId == null
          ? "workspace_shared"
          : "agent_only",
    identity,
    mode,
    connection,
    platformApp,
    credentials,
    settings,
    stage,
    publication,
    installationState,
    rootRef: progression.rootRef,
    candidate: connection.type === "CANDIDATE" ? connection.candidate : null,
    availability: availabilityState,
    canContinue: ready,
    onIdentity: (next) => {
      if (pending.current || identity === next) {
        return;
      }
      abandon();
      const sole = soleGitHubMethod(next, availabilityState);
      setSelection(
        sole == null
          ? { type: "IDENTITY", identity: next }
          : { type: "METHOD", mode: sole },
      );
      progression.advance(sole == null ? "METHOD" : "CONNECTION");
    },
    onMode: (next) => {
      if (pending.current || mode === next) {
        return;
      }
      abandon();
      setSelection({ type: "METHOD", mode: next });
      progression.advance("CONNECTION");
    },
    onCredentials: (next) => {
      if (pending.current) {
        return;
      }
      epoch.current.next();
      if (
        mode === "github_app_platform" &&
        next.installationIds.join("\0") !==
          credentials.installationIds.join("\0")
      ) {
        installationSelectionTouched.current = true;
      }
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
      const next =
        stage === "CONNECTION"
          ? "FEATURES"
          : stage === "FEATURES"
            ? "RUNTIME"
            : "REVIEW";
      setStage(next);
      progression.advance(next);
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
        router.push(listPath);
      }
    },
    onInspect: () => {
      if (embedded) {
        onComplete?.();
      } else {
        router.push(listPath);
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
