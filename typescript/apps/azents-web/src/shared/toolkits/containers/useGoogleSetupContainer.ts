"use client";
import { readSessionStorageValue, useSessionStorage } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  googleGroupsUsable,
  googlePresetGroups,
  googleScopesForGroups,
} from "../google-access";
import {
  deserializeGoogleDraft,
  emptyGoogleMetadata,
  GOOGLE_DRAFT_KEY,
  googleDraftMatches,
  googleReviewDecision,
  googleUsableSelection,
  reconcileGoogleSelection,
  sameGoogleSelection,
} from "../google-editor";
import {
  deserializeGoogleResume,
  GOOGLE_RESUME_KEY,
  googleAgentReturnPath,
  googleResumeMatches,
  googleReturnPath,
  googleStateDigest,
  sameGoogleResumeAttempt,
} from "../google-resume";
import { canPublishGoogleReview } from "../google-types";
import { useGooglePickerContainer } from "./useGooglePickerContainer";
import type { GoogleEditorDraft } from "../google-editor";
import type { GoogleResume } from "../google-resume";
import type {
  GoogleFlowState,
  GoogleMetadata,
  GooglePreparationState,
  GoogleSavedState,
  GoogleSetupProps,
} from "../google-types";
import type {
  PersonalToolkitOrigin,
  ToolkitOwnerScope,
} from "../toolkit-owner-scope";
import type {
  GooglePublishedOutput,
  GoogleService,
  GoogleToolGroup,
} from "@azents/public-client";

export type GoogleSetupContainerProps = ToolkitOwnerScope & {
  navigationOrigin?: PersonalToolkitOrigin;
  toolkitId?: string;
  embedded?: boolean;
  initialDescription?: string;
  initialMetadata?: GoogleMetadata;
  recoveryOnly?: boolean;
  returnAgentId?: string;
  onComplete?: () => void;
  onPendingChange?: (pending: boolean) => void;
  onAbandonReady?: (abandon: (() => void) | null) => void;
  onCloseGuardReady?: (guard: (() => boolean) | null) => void;
  onRecovered?: () => void;
};
export function useGoogleSetupContainer(
  props: GoogleSetupContainerProps,
): GoogleSetupProps {
  const {
    toolkitId,
    embedded = false,
    onComplete,
    onPendingChange,
    onAbandonReady,
  } = props;
  const t = useTranslations("googleToolkit"),
    router = useRouter(),
    utils = trpc.useUtils();
  const handle = props.handle,
    agentId = "agentId" in props ? props.agentId : null,
    personal = "owner" in props;
  const scope = useMemo<ToolkitOwnerScope>(
    () =>
      personal
        ? { owner: "user", handle }
        : { handle, ...(agentId != null && { agentId }) },
    [personal, handle, agentId],
  );
  const preparationQuery = trpc.toolkit.google.preparation.useQuery(scope, {
    retry: false,
  });
  const statusQuery = trpc.toolkit.google.status.useQuery(
    { ...scope, toolkitId: toolkitId ?? "" },
    { enabled: toolkitId != null, retry: false },
  );
  const connect = trpc.toolkit.google.connect.useMutation(),
    reconnect = trpc.toolkit.google.reconnect.useMutation(),
    confirm = trpc.toolkit.google.confirm.useMutation(),
    reconnectConfirm = trpc.toolkit.google.reconnectConfirm.useMutation();
  const cancel = trpc.toolkit.google.cancel.useMutation(),
    disconnect = trpc.toolkit.google.disconnect.useMutation(),
    servicesUpdate = trpc.toolkit.google.services.useMutation({ retry: false });
  const [, saveResume, clearResume] = useSessionStorage<GoogleResume | null>({
    key: GOOGLE_RESUME_KEY,
    defaultValue: null,
    deserialize: deserializeGoogleResume,
  });
  const [, saveDraft, clearDraft] = useSessionStorage<GoogleEditorDraft | null>(
    {
      key: GOOGLE_DRAFT_KEY,
      defaultValue: null,
      deserialize: deserializeGoogleDraft,
    },
  );
  const [flow, setFlow] = useState<GoogleFlowState>({ type: "SELECT" });
  const [services, setServices] = useState<GoogleService[]>([]),
    [toolGroups, setToolGroups] = useState<GoogleToolGroup[]>([]),
    [timeout, setTimeoutValue] = useState(30);
  const initialMetadata = props.initialMetadata ?? {
    ...emptyGoogleMetadata,
    description: props.initialDescription ?? "",
  };
  const [metadata, setMetadata] = useState<GoogleMetadata>(initialMetadata),
    baselineMetadata = useRef(initialMetadata),
    draftRevision = useRef<number | null>(null);
  const [savingServices, setSavingServices] = useState(false),
    [operationError, setOperationError] = useState<string | null>(null),
    [disconnectConfirmation, setDisconnectConfirmation] = useState(false),
    [cancelling, setCancelling] = useState(false),
    [disconnecting, setDisconnecting] = useState(false);
  const epoch = useRef(0),
    ownerIdentity = useRef(
      JSON.stringify([personal, handle, agentId, toolkitId]),
    ),
    mounted = useRef(true),
    active = useRef<GoogleResume | null>(null),
    authorizationPurpose = useRef<NonNullable<GoogleResume["purpose"]> | null>(
      null,
    ),
    pending = useRef(false),
    initialized = useRef(false),
    automatic = useRef<string | null>(null),
    startedRecovery = useRef(false),
    rootRef = useRef<HTMLDivElement>(null);
  const catalog = preparationQuery.data?.tool_group_catalog ?? [];
  const activeGroups = toolGroups.filter((id) =>
    catalog.some(
      (group) => group.group === id && services.includes(group.service),
    ),
  );
  const review =
    flow.type === "REVIEW" || flow.type === "CONFIRMING" ? flow.review : null;
  const reviewDecision =
    review == null
      ? null
      : toolkitId != null && statusQuery.data == null
        ? "UNUSABLE"
        : googleReviewDecision(
            review,
            toolkitId == null ? null : (statusQuery.data ?? null),
            catalog,
          );
  const reviewAllowed =
    review != null &&
    canPublishGoogleReview(review, review.services, Date.now()) &&
    googleGroupsUsable(
      review.services,
      review.tool_groups,
      catalog,
      review.accesses,
    );
  const preparation: GooglePreparationState = preparationQuery.isPending
    ? { type: "LOADING" }
    : preparationQuery.isError
      ? { type: "ERROR", message: t("preparationFailed") }
      : { type: "READY", detail: preparationQuery.data };
  const saved: GoogleSavedState =
    toolkitId == null
      ? { type: "NEW" }
      : statusQuery.isPending
        ? { type: "LOADING" }
        : statusQuery.isError
          ? { type: "ERROR", message: t("statusFailed") }
          : { type: "READY", detail: statusQuery.data };
  const servicesDirty =
    saved.type === "READY" &&
    (!sameGoogleSelection(services, saved.detail.services) ||
      !sameGoogleSelection(toolGroups, saved.detail.tool_groups) ||
      timeout !== saved.detail.timeout);
  const settingsDirty =
    servicesDirty ||
    JSON.stringify(metadata) !== JSON.stringify(baselineMetadata.current);
  const busy =
    flow.type === "AUTHORIZING" ||
    flow.type === "VERIFYING" ||
    flow.type === "CONFIRMING" ||
    cancelling ||
    disconnecting ||
    savingServices ||
    (flow.type === "UNKNOWN" && flow.checking);
  useEffect(() => {
    const identity = JSON.stringify([personal, handle, agentId, toolkitId]);
    if (ownerIdentity.current !== identity) {
      ownerIdentity.current = identity;
      initialized.current = false;
      active.current = null;
      authorizationPurpose.current = null;
      automatic.current = null;
      startedRecovery.current = false;
      pending.current = false;
      draftRevision.current = null;
      baselineMetadata.current = initialMetadata;
      setMetadata(initialMetadata);
      setServices([]);
      setToolGroups([]);
      setTimeoutValue(30);
      setFlow({ type: "SELECT" });
      setOperationError(null);
      setSavingServices(false);
      setCancelling(false);
      setDisconnecting(false);
      setDisconnectConfirmation(false);
    }
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a real owner/target transition resets the draft, not metadata prop refetches or Strict Mode probing.
  }, [personal, handle, agentId, toolkitId]);
  const current = (operation: number): boolean =>
    mounted.current && epoch.current === operation;
  const readResume = (): GoogleResume | null =>
    readSessionStorageValue<GoogleResume | null>({
      key: GOOGLE_RESUME_KEY,
      deserialize: deserializeGoogleResume,
    }) ?? null;
  const writeResume = (context: GoogleResume): void => {
    active.current = context;
    saveResume(context);
  };
  const close = (): void => {
    if (onComplete != null) {
      onComplete();
    } else {
      router.push(
        "owner" in scope
          ? `/w/${encodeURIComponent(handle)}/personal-tools`
          : props.returnAgentId != null
            ? googleAgentReturnPath(handle, props.returnAgentId)
            : scope.agentId != null
              ? googleAgentReturnPath(handle, scope.agentId)
              : `/w/${encodeURIComponent(handle)}/toolkits`,
      );
    }
  };
  const reset = (): void => {
    if (
      active.current != null &&
      sameGoogleResumeAttempt(readResume(), active.current)
    ) {
      clearResume();
    }
    active.current = null;
    automatic.current = null;
    authorizationPurpose.current = null;
    setOperationError(null);
    setFlow({ type: "SELECT" });
  };
  const invalidate = async (): Promise<void> => {
    if ("owner" in scope) {
      await Promise.all([
        utils.personalToolkit.list.invalidate({ handle }),
        utils.personalToolkit.get.invalidate({ handle }),
        utils.personalToolkit.accessForAgent.invalidate({ handle }),
        utils.toolkit.google.status.invalidate(),
      ]);
    } else {
      await Promise.all([
        utils.toolkit.listConfigs.invalidate(),
        utils.toolkit.listAvailableConfigs.invalidate(),
        utils.toolkit.listAgentManagement.invalidate(),
        utils.toolkit.listAgentToolkits.invalidate(),
        utils.toolkit.getConfig.invalidate(),
        utils.toolkit.getAgentConfig.invalidate(),
        utils.toolkit.google.status.invalidate(),
      ]);
    }
  };
  const finish = async (
    outcome: GooglePublishedOutput,
    context: GoogleResume,
  ): Promise<void> => {
    if (!sameGoogleResumeAttempt(readResume(), context)) {
      return;
    }
    const generation = epoch.current;
    let effective = outcome;
    if (outcome.current) {
      try {
        const published = await utils.toolkit.google.status.fetch(
          { ...scope, toolkitId: outcome.toolkit_id },
          { retry: false, staleTime: 0 },
        );
        if (
          !current(generation) ||
          !sameGoogleResumeAttempt(readResume(), context)
        ) {
          return;
        }
        effective = {
          ...outcome,
          current: published.connection_id === outcome.connection_id,
        };
        if (effective.current) {
          const retained = readSessionStorageValue<GoogleEditorDraft | null>({
            key: GOOGLE_DRAFT_KEY,
            deserialize: deserializeGoogleDraft,
          });
          const recovery = context.purpose === "RECOVER";
          const draft =
            retained != null &&
            googleDraftMatches(retained, scope, toolkitId, context.attemptId)
              ? retained
              : null;
          if (recovery && draft?.baseline != null) {
            setServices(
              reconcileGoogleSelection(
                draft.baseline.services,
                draft.services,
                published.services,
              ),
            );
            setToolGroups(
              reconcileGoogleSelection(
                draft.baseline.toolGroups,
                draft.toolGroups,
                published.tool_groups,
              ),
            );
            setTimeoutValue(
              draft.timeout === draft.baseline.timeout
                ? published.timeout
                : draft.timeout,
            );
          } else {
            setServices(published.services);
            setToolGroups(published.tool_groups);
            setTimeoutValue(published.timeout);
          }
          // Only our publication increment may rebase retained metadata edits.
          if (
            draftRevision.current != null &&
            published.revision === draftRevision.current + 1
          ) {
            draftRevision.current = published.revision;
          }
          if (context.purpose === "CONNECT" || context.purpose === "APPLY") {
            baselineMetadata.current = metadata;
            if (draft != null) {
              clearDraft();
            }
          }
        }
      } catch {
        if (
          current(generation) &&
          sameGoogleResumeAttempt(readResume(), context)
        ) {
          writeResume({ ...context, phase: "UNKNOWN" });
          setFlow({
            type: "UNKNOWN",
            checking: false,
            message: t("statusFailed"),
          });
        }
        return;
      }
    }
    if (
      !current(generation) ||
      !sameGoogleResumeAttempt(readResume(), context)
    ) {
      return;
    }
    active.current = null;
    clearResume();
    setFlow({ type: "COMPLETE", outcome: effective });
    // A refresh failure cannot turn an acknowledged publication into a failed save.
    void invalidate().catch(() => {
      if (current(generation)) {
        setOperationError(t("statusFailed"));
      }
    });
    if (effective.current && (toolkitId == null || props.recoveryOnly)) {
      props.onRecovered?.();
      close();
    }
  };
  useEffect(() => {
    if (
      initialized.current ||
      preparationQuery.data == null ||
      preparationQuery.isError ||
      (toolkitId != null && (statusQuery.data == null || statusQuery.isError))
    ) {
      return;
    }
    initialized.current = true;
    const context = readResume(),
      owns = context != null && googleResumeMatches(context, scope, toolkitId);
    const draft = readSessionStorageValue<GoogleEditorDraft | null>({
      key: GOOGLE_DRAFT_KEY,
      deserialize: deserializeGoogleDraft,
    });
    if (
      draft != null &&
      googleDraftMatches(
        draft,
        scope,
        toolkitId,
        owns ? context.attemptId : null,
      )
    ) {
      setMetadata(draft.metadata);
      setServices(draft.services);
      setToolGroups(draft.toolGroups);
      setTimeoutValue(draft.timeout);
      draftRevision.current = draft.revision;
    } else if (statusQuery.data != null) {
      setServices(statusQuery.data.services);
      setToolGroups(statusQuery.data.tool_groups);
      setTimeoutValue(statusQuery.data.timeout);
      draftRevision.current = statusQuery.data.revision;
    }
    if (!owns) {
      return;
    }
    active.current = context;
    authorizationPurpose.current =
      context.purpose ?? (toolkitId == null ? "CONNECT" : "RECOVER");
    if (context.phase === "PUBLISHING" || context.phase === "UNKNOWN") {
      setFlow({ type: "UNKNOWN", checking: false, message: null });
      return;
    }
    if (context.phase === "FAILED") {
      setFlow({ type: "ERROR", message: t("verificationFailed") });
      return;
    }
    if (Date.parse(context.expiresAt) <= Date.now()) {
      setFlow({ type: "ERROR", message: t("expired") });
      return;
    }
    if (context.phase === "AUTHORIZING") {
      setFlow({ type: "ERROR", message: t("authorizationIncomplete") });
      return;
    }
    setFlow({ type: "VERIFYING" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- latch successful hydration; refetches must not overwrite or rebase an unapplied draft.
  }, [
    personal,
    handle,
    agentId,
    toolkitId,
    preparationQuery.isPending,
    statusQuery.isPending,
    preparationQuery.isError,
    statusQuery.isError,
    preparationQuery.data,
    statusQuery.data,
  ]);
  useEffect(() => {
    const context = active.current;
    if (
      flow.type !== "VERIFYING" ||
      context == null ||
      !googleResumeMatches(context, scope, toolkitId) ||
      !sameGoogleResumeAttempt(readResume(), context)
    ) {
      return;
    }
    let live = true;
    const operation = ++epoch.current;
    const owns = (): boolean =>
      live &&
      current(operation) &&
      sameGoogleResumeAttempt(active.current, context) &&
      sameGoogleResumeAttempt(readResume(), context);
    void utils.toolkit.google.review
      .fetch(
        { ...scope, attemptId: context.attemptId },
        { retry: false, staleTime: 0 },
      )
      .then((result) => {
        if (
          owns() &&
          result.attempt_id === context.attemptId &&
          result.reconnect_toolkit_id === (toolkitId ?? null)
        ) {
          setFlow({ type: "REVIEW", review: result });
        }
      })
      .catch(() => {
        if (owns()) {
          setFlow({ type: "ERROR", message: t("verificationFailed") });
        }
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- repeat only the safe review read for a verifying exact owner/target; query refetches do not rehydrate the draft.
  }, [flow.type, personal, handle, agentId, toolkitId]);
  useEffect(() => {
    pending.current = busy || flow.type === "UNKNOWN";
    onPendingChange?.(pending.current);
    return () => onPendingChange?.(false);
  }, [busy, flow.type, onPendingChange]);
  async function authorize(
    purpose: NonNullable<GoogleResume["purpose"]>,
  ): Promise<void> {
    if (
      pending.current ||
      preparation.type !== "READY" ||
      preparation.detail.status !== "configured_unverified"
    ) {
      return;
    }
    authorizationPurpose.current = purpose;
    const recovery = purpose === "RECOVER",
      selectedServices =
        recovery && saved.type === "READY" ? saved.detail.services : services,
      selectedGroups =
        recovery && saved.type === "READY"
          ? saved.detail.tool_groups
          : activeGroups;
    if (selectedServices.length === 0 || selectedGroups.length === 0) {
      setOperationError(t("selectRequired"));
      return;
    }
    pending.current = true;
    const operation = ++epoch.current;
    setOperationError(null);
    setFlow({ type: "AUTHORIZING" });
    try {
      const desired = {
        services: selectedServices,
        tool_groups: selectedGroups,
        oauth_request_scopes: googleScopesForGroups(selectedGroups, catalog),
        timeout:
          recovery && saved.type === "READY" ? saved.detail.timeout : timeout,
      };
      const result =
        toolkitId == null
          ? await connect.mutateAsync({ ...scope, desired })
          : await reconnect.mutateAsync({ ...scope, toolkitId, desired });
      const state = new URL(result.authorization_url).searchParams.get("state");
      if (state == null) {
        throw new Error("Google authorization state is missing.");
      }
      const stateDigest = await googleStateDigest(state);
      if (!current(operation)) {
        return;
      }
      saveDraft({
        ...scope,
        toolkitId,
        attemptId: result.attempt_id,
        expiresAt: result.expires_at,
        metadata,
        services,
        toolGroups,
        timeout,
        revision: draftRevision.current,
        baseline:
          saved.type === "READY"
            ? {
                services: saved.detail.services,
                toolGroups: saved.detail.tool_groups,
                timeout: saved.detail.timeout,
              }
            : null,
      });
      writeResume({
        ...scope,
        toolkitId,
        attemptId: result.attempt_id,
        expiresAt: result.expires_at,
        stateDigest,
        phase: "AUTHORIZING",
        purpose,
        ...(props.returnAgentId != null && {
          returnAgentId: props.returnAgentId,
        }),
        returnPath:
          props.returnAgentId != null
            ? googleAgentReturnPath(handle, props.returnAgentId)
            : googleReturnPath(scope, toolkitId, props.navigationOrigin),
      });
      window.location.assign(result.authorization_url);
    } catch {
      if (current(operation)) {
        pending.current = false;
        setFlow({ type: "ERROR", message: t("authorizationFailed") });
      }
    }
  }
  const metadataInput = (): {
    expected_revision: number;
    name: string;
    slug: string;
    description: string | null;
    prompt: string | null;
    enabled: boolean;
    always_expose_tools: boolean;
  } => ({
    expected_revision: draftRevision.current ?? -1,
    name: metadata.name,
    slug: metadata.slug,
    description: metadata.description || null,
    prompt: metadata.prompt || null,
    enabled: metadata.enabled,
    always_expose_tools: metadata.alwaysExposeTools,
  });
  async function publish(): Promise<void> {
    if (
      pending.current ||
      flow.type !== "REVIEW" ||
      reviewDecision !== "NORMAL" ||
      active.current == null ||
      !sameGoogleResumeAttempt(readResume(), active.current) ||
      !reviewAllowed
    ) {
      return;
    }
    const result = flow.review,
      context = active.current,
      selection = googleUsableSelection(result, catalog);
    if (selection.services.length === 0 || selection.toolGroups.length === 0) {
      return;
    }
    if (context.purpose === "APPLY" || context.purpose === "CONNECT") {
      const draft = readSessionStorageValue<GoogleEditorDraft | null>({
        key: GOOGLE_DRAFT_KEY,
        deserialize: deserializeGoogleDraft,
      });
      if (
        draft == null ||
        !googleDraftMatches(draft, scope, toolkitId, context.attemptId)
      ) {
        setOperationError(t("draftUnavailable"));
        return;
      }
    }
    pending.current = true;
    const operation = ++epoch.current;
    setOperationError(null);
    setFlow({ type: "CONFIRMING", review: result });
    writeResume({ ...context, phase: "PUBLISHING" });
    try {
      const settings = {
        services: selection.services,
        tool_groups: selection.toolGroups,
        oauth_request_scopes: result.oauth_request_scopes,
        timeout: result.timeout,
      };
      const outcome =
        toolkitId == null
          ? await confirm.mutateAsync({
              ...scope,
              attemptId: context.attemptId,
              settings: {
                ...settings,
                name: metadata.name.trim() || null,
                slug: metadata.slug.trim() || null,
                description: metadata.description || null,
                prompt: metadata.prompt || null,
                enabled: metadata.enabled,
                always_expose_tools: metadata.alwaysExposeTools,
              },
            })
          : await reconnectConfirm.mutateAsync({
              ...scope,
              attemptId: context.attemptId,
              settings: {
                ...settings,
                ...(context.purpose === "APPLY" && {
                  metadata: metadataInput(),
                }),
              },
            });
      if (current(operation)) {
        await finish(outcome, context);
      }
    } catch {
      if (
        current(operation) &&
        sameGoogleResumeAttempt(readResume(), context)
      ) {
        writeResume({ ...context, phase: "UNKNOWN" });
        setFlow({ type: "UNKNOWN", checking: false, message: null });
      }
    } finally {
      if (current(operation)) {
        pending.current = false;
      }
    }
  }
  useEffect(() => {
    const context = active.current;
    if (
      flow.type !== "REVIEW" ||
      reviewDecision !== "NORMAL" ||
      context?.purpose == null ||
      automatic.current === context.attemptId ||
      pending.current
    ) {
      return;
    }
    automatic.current = context.attemptId;
    void publish();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- exact normal attempt publishes once; UNKNOWN never resubmits.
  }, [flow, reviewDecision]);
  useEffect(() => {
    if (
      !props.recoveryOnly ||
      startedRecovery.current ||
      !initialized.current ||
      active.current != null ||
      saved.type !== "READY" ||
      preparation.type !== "READY"
    ) {
      return;
    }
    let live = true;
    void Promise.resolve().then(() => {
      if (!live || startedRecovery.current) {
        return;
      }
      startedRecovery.current = true;
      void authorize("RECOVER");
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one direct recovery after saved target admission.
  }, [props.recoveryOnly, saved.type, preparation.type, services]);
  async function checkOutcome(): Promise<void> {
    const context = active.current;
    if (context == null || (flow.type === "UNKNOWN" && flow.checking)) {
      return;
    }
    const operation = ++epoch.current;
    setFlow({ type: "UNKNOWN", checking: true, message: null });
    try {
      const outcome = await utils.toolkit.google.outcome.fetch(
        { ...scope, attemptId: context.attemptId },
        { retry: false, staleTime: 0 },
      );
      if (current(operation)) {
        await finish(outcome, context);
      }
    } catch {
      if (current(operation)) {
        setFlow({
          type: "UNKNOWN",
          checking: false,
          message: t("outcomeUnavailable"),
        });
      }
    }
  }
  const cancelExact = useCallback(
    async (restart = false): Promise<void> => {
      if (
        (pending.current && flow.type !== "UNKNOWN") ||
        (flow.type === "UNKNOWN" && flow.checking)
      ) {
        return;
      }
      const context = active.current,
        purpose =
          context?.purpose ??
          authorizationPurpose.current ??
          (toolkitId == null ? "CONNECT" : "RECOVER"),
        operation = ++epoch.current;
      if (context == null) {
        reset();
        if (restart) {
          pending.current = false;
          authorizationPurpose.current = purpose;
          await authorize(purpose);
        }
        return;
      }
      setCancelling(true);
      setOperationError(null);
      try {
        const result = await cancel.mutateAsync({
          ...scope,
          attemptId: context.attemptId,
        });
        if (!sameGoogleResumeAttempt(readResume(), context)) {
          return;
        }
        if (!current(operation)) {
          if (result.publication == null) {
            clearResume();
          } else {
            saveResume({ ...context, phase: "UNKNOWN" });
          }
          return;
        }
        if (result.publication != null) {
          await finish(result.publication, context);
        } else {
          reset();
          if (restart) {
            pending.current = false;
            setCancelling(false);
            authorizationPurpose.current = purpose;
            await authorize(purpose);
          } else if (props.recoveryOnly) {
            close();
          }
        }
      } catch {
        if (current(operation)) {
          setOperationError(t("cancelFailed"));
        }
      } finally {
        if (current(operation)) {
          setCancelling(false);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bind the current flow snapshot while exact owner/attempt refs fence delayed cancellation.
    [personal, handle, agentId, toolkitId, flow],
  );
  useEffect(() => {
    onAbandonReady?.(() => {
      void cancelExact();
    });
    return () => onAbandonReady?.(null);
  }, [cancelExact, onAbandonReady]);
  const guardClose = (): boolean => {
    if (pending.current) {
      return false;
    }
    if (settingsDirty && !window.confirm(t("discardDraft"))) {
      return false;
    }
    clearDraft();
    if (active.current != null) {
      void cancelExact();
    }
    return true;
  };
  useEffect(() => {
    props.onCloseGuardReady?.(guardClose);
    return () => props.onCloseGuardReady?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- register the current draft/attempt guard with its owning editor.
  }, [props.onCloseGuardReady, settingsDirty, busy, cancelExact]);
  useEffect(() => {
    if (review != null && reviewDecision !== "NORMAL") {
      rootRef.current
        ?.querySelector<HTMLElement>("#google-review-heading")
        ?.focus();
    }
  }, [review, reviewDecision]);
  const pickerAvailable =
    saved.type === "READY" &&
    saved.detail.status === "connected" &&
    saved.detail.renewable &&
    saved.detail.connection_id != null &&
    saved.detail.services.includes("drive") &&
    (saved.detail.granted_scopes?.includes(
      "https://www.googleapis.com/auth/drive.file",
    ) ??
      false) &&
    preparation.type === "READY" &&
    preparation.detail.picker_status === "configured_unverified" &&
    !servicesDirty &&
    !busy &&
    (flow.type === "SELECT" || flow.type === "COMPLETE");
  const pickerControls = useGooglePickerContainer({
    enabled: pickerAvailable,
    contextKey: `${handle}:${agentId}:${toolkitId}:${saved.type === "READY" ? `${saved.detail.revision}:${saved.detail.connection_id}:${saved.detail.status}` : saved.type}`,
    unavailableMessage: t("pickerFailed"),
    expiredMessage: t("pickerExpired"),
    issue: async () => {
      if (
        saved.type !== "READY" ||
        saved.detail.connection_id == null ||
        toolkitId == null
      ) {
        throw new Error("Google Picker requires a current saved connection.");
      }
      try {
        return await utils.client.toolkit.google.pickerToken.mutate({
          ...scope,
          toolkitId,
          expectedRevision: saved.detail.revision,
          connectionId: saved.detail.connection_id,
        });
      } catch {
        await invalidate();
        throw new Error("Google Picker is unavailable. Reload the connection.");
      }
    },
  });
  async function apply(): Promise<void> {
    if (toolkitId == null) {
      await authorize("CONNECT");
      return;
    }
    if (pending.current || saved.type !== "READY" || !settingsDirty) {
      return;
    }
    const granted = new Set(saved.detail.granted_tools);
    if (
      catalog.some(
        (group) =>
          activeGroups.includes(group.group) &&
          !(
            saved.detail.services.includes(group.service) &&
            saved.detail.tool_groups.includes(group.group)
          ) &&
          group.operations.some((op) => !granted.has(op)),
      )
    ) {
      await authorize("APPLY");
      return;
    }
    pending.current = true;
    const operation = ++epoch.current;
    setSavingServices(true);
    setOperationError(null);
    pickerControls.onClosePicker();
    let updated: Awaited<ReturnType<typeof servicesUpdate.mutateAsync>>;
    try {
      updated = await servicesUpdate.mutateAsync({
        ...scope,
        toolkitId,
        expectedRevision: draftRevision.current ?? saved.detail.revision,
        services,
        toolGroups,
        timeout,
        ...(JSON.stringify(metadata) !==
          JSON.stringify(baselineMetadata.current) && {
          metadata: metadataInput(),
        }),
      });
    } catch (error) {
      if (current(operation)) {
        setOperationError(
          error instanceof Error ? error.message : t("serviceSaveFailed"),
        );
      }
      return;
    } finally {
      if (current(operation)) {
        pending.current = false;
        setSavingServices(false);
      }
    }
    if (current(operation)) {
      draftRevision.current = updated.revision;
      baselineMetadata.current = metadata;
      clearDraft();
      close();
      void invalidate().catch(() => {
        if (current(operation)) {
          setOperationError(t("statusFailed"));
        }
      });
    }
  }
  async function disconnectSaved(): Promise<void> {
    if (toolkitId == null || pending.current) {
      return;
    }
    const operation = ++epoch.current;
    setDisconnecting(true);
    setOperationError(null);
    try {
      await disconnect.mutateAsync({ ...scope, toolkitId });
      if (current(operation)) {
        reset();
        setDisconnectConfirmation(false);
        await invalidate();
      }
    } catch {
      if (current(operation)) {
        setOperationError(t("disconnectFailed"));
      }
    } finally {
      if (current(operation)) {
        setDisconnecting(false);
      }
    }
  }
  return {
    preparation,
    saved,
    flow,
    services,
    toolGroups,
    timeout,
    metadata,
    reconnect: toolkitId != null,
    ownership:
      "owner" in scope ? "user" : scope.agentId != null ? "agent" : "workspace",
    cancelling,
    disconnecting,
    savingServices,
    servicesDirty,
    settingsDirty,
    recoveryOnly: props.recoveryOnly,
    reviewDecision,
    pickerAvailable,
    ...pickerControls,
    disconnectConfirmation,
    operationError,
    rootRef,
    embedded,
    onServiceChange: (service, selected) => {
      pickerControls.onClosePicker();
      setServices((current) =>
        selected
          ? Array.from(new Set([...current, service]))
          : current.filter((item) => item !== service),
      );
    },
    onGroupChange: (group, selected) =>
      setToolGroups((current) =>
        selected
          ? Array.from(new Set([...current, group]))
          : current.filter((id) => id !== group),
      ),
    onPresetChange: (service, preset) =>
      setToolGroups((current) => [
        ...current.filter(
          (id) =>
            !catalog.some(
              (group) => group.group === id && group.service === service,
            ),
        ),
        ...googlePresetGroups(preset, [service], catalog),
      ]),
    onSaveServices: apply,
    onApply: () => {
      void apply();
    },
    onReauthenticate: () => {
      void authorize("RECOVER");
    },
    onClose: () => {
      if (guardClose()) {
        close();
      }
    },
    onTimeoutChange: setTimeoutValue,
    onMetadataChange: (patch) =>
      setMetadata((current) => ({ ...current, ...patch })),
    onAuthorize: () => {
      void authorize(toolkitId == null ? "CONNECT" : "APPLY");
    },
    onRetryAuthorization: () => cancelExact(true),
    onCheckOutcome: checkOutcome,
    onCancel: () => {
      void cancelExact();
    },
    onRefresh: () => {
      void utils.toolkit.google.preparation.invalidate(scope);
      void utils.toolkit.google.status.invalidate();
    },
    onAskDisconnect: () => setDisconnectConfirmation(true),
    onDismissDisconnect: () => setDisconnectConfirmation(false),
    onDisconnect: () => {
      void disconnectSaved();
    },
  };
}
