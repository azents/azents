"use client";
import {
  readSessionStorageValue,
  useReducedMotion,
  useSessionStorage,
} from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { trpc } from "@/trpc/client";
import { revealGitHubWizardHeading } from "../github-wizard-progression";
import {
  deserializeGoogleResume,
  GOOGLE_RESUME_KEY,
  googleResumeMatches,
  googleReturnPath,
  googleStateDigest,
  sameGoogleResumeAttempt,
} from "../google-resume";
import { canPublishGoogleReview } from "../google-types";
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
  GoogleReview,
  GoogleTask,
} from "@azents/public-client";

export type GoogleSetupContainerProps = ToolkitOwnerScope & {
  navigationOrigin?: PersonalToolkitOrigin;
  toolkitId?: string;
  embedded?: boolean;
  initialDescription?: string;
  onComplete?: () => void;
  onPendingChange?: (pending: boolean) => void;
  onAbandonReady?: (abandon: (() => void) | null) => void;
};
export function useGoogleSetupContainer(
  props: GoogleSetupContainerProps,
): GoogleSetupProps {
  const {
    toolkitId,
    embedded = false,
    initialDescription = "",
    onComplete,
    onPendingChange,
    onAbandonReady,
  } = props;
  const t = useTranslations("googleToolkit");
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
  const preparationQuery = trpc.toolkit.google.preparation.useQuery(scope, {
    retry: false,
  });
  const statusQuery = trpc.toolkit.google.status.useQuery(
    { ...scope, toolkitId: toolkitId ?? "" },
    { enabled: toolkitId != null, retry: false },
  );
  const connect = trpc.toolkit.google.connect.useMutation();
  const reconnect = trpc.toolkit.google.reconnect.useMutation();
  const confirm = trpc.toolkit.google.confirm.useMutation();
  const reconnectConfirm = trpc.toolkit.google.reconnectConfirm.useMutation();
  const cancel = trpc.toolkit.google.cancel.useMutation();
  const disconnect = trpc.toolkit.google.disconnect.useMutation();
  const [, saveResume, clearResume] = useSessionStorage<GoogleResume | null>({
    key: GOOGLE_RESUME_KEY,
    defaultValue: null,
    deserialize: deserializeGoogleResume,
  });
  const [flow, setFlow] = useState<GoogleFlowState>({ type: "SELECT" });
  const [tasks, setTasks] = useState<GoogleTask[]>([]);
  const [timeout, setTimeoutValue] = useState(30);
  const [metadata, setMetadata] = useState<GoogleMetadata>({
    name: "",
    slug: "",
    description: initialDescription,
    prompt: "",
    enabled: true,
    alwaysExposeTools: false,
  });
  const [acknowledged, setAcknowledged] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [disconnectConfirmation, setDisconnectConfirmation] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const active = useRef<GoogleResume | null>(null);
  const pending = useRef(false);
  const restored = useRef(false);
  const initializedSaved = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const [focusRequest, setFocusRequest] = useState(0);
  const focused = useRef(0);
  useLayoutEffect(() => {
    if (focusRequest === focused.current) {
      return;
    }
    const heading = rootRef.current?.querySelector<HTMLElement>(
      "#google-review-heading",
    );
    if (heading == null) {
      return;
    }
    focused.current = focusRequest;
    revealGitHubWizardHeading(heading, reducedMotion === true);
  }, [focusRequest, reducedMotion]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current += 1;
    };
  }, [handle, agentId, toolkitId]);
  const isCurrent = (operation: number): boolean =>
    mounted.current && epoch.current === operation;
  const writeResume = (context: GoogleResume): void => {
    active.current = context;
    saveResume(context);
  };
  const readResume = (): GoogleResume | null =>
    readSessionStorageValue<GoogleResume | null>({
      key: GOOGLE_RESUME_KEY,
      deserialize: deserializeGoogleResume,
    }) ?? null;
  const reset = (): void => {
    if (
      active.current != null &&
      sameGoogleResumeAttempt(readResume(), active.current)
    ) {
      clearResume();
    }
    active.current = null;
    setAcknowledged(false);
    setOperationError(null);
    setFlow({ type: "SELECT" });
  };
  const invalidate = async (): Promise<void> => {
    if ("owner" in scope) {
      await Promise.all([
        utils.personalToolkit.list.invalidate({ handle: scope.handle }),
        utils.personalToolkit.get.invalidate({ handle: scope.handle }),
        utils.personalToolkit.accessForAgent.invalidate({
          handle: scope.handle,
        }),
        utils.toolkit.google.status.invalidate(),
      ]);
      return;
    }
    await Promise.all([
      utils.toolkit.listConfigs.invalidate(),
      utils.toolkit.listAvailableConfigs.invalidate(),
      utils.toolkit.listAgentManagement.invalidate(),
      utils.toolkit.listAgentToolkits.invalidate(),
      utils.toolkit.getConfig.invalidate(),
      utils.toolkit.getAgentConfig.invalidate(),
      utils.toolkit.google.status.invalidate(),
    ]);
  };
  const acceptReview = (review: GoogleReview): void => {
    setTasks(review.requested_tasks);
    setTimeoutValue(review.timeout);
    setAcknowledged(false);
    setFlow({ type: "REVIEW", review });
  };
  const finish = async (
    outcome: GooglePublishedOutput,
    context: GoogleResume,
  ): Promise<void> => {
    if (!sameGoogleResumeAttempt(readResume(), context)) {
      return;
    }
    const finishingGeneration = epoch.current;
    active.current = null;
    clearResume();
    setAcknowledged(false);
    setFlow({ type: "COMPLETE", outcome });
    try {
      await invalidate();
    } catch {
      if (isCurrent(finishingGeneration) && readResume() == null) {
        setOperationError(t("statusFailed"));
      }
    }
    if (
      toolkitId == null &&
      outcome.current &&
      isCurrent(finishingGeneration) &&
      readResume() == null
    ) {
      if (onComplete != null) {
        onComplete();
      } else {
        router.push(
          "owner" in scope
            ? `/w/${encodeURIComponent(handle)}/personal-tools`
            : scope.agentId == null
              ? `/w/${scope.handle}/toolkits`
              : googleReturnPath(scope),
        );
      }
    }
  };
  useEffect(() => {
    if (
      initializedSaved.current ||
      statusQuery.data == null ||
      active.current != null
    ) {
      return;
    }
    initializedSaved.current = true;
    setTasks(statusQuery.data.selected_tasks);
    setTimeoutValue(statusQuery.data.timeout);
  }, [statusQuery.data]);
  useEffect(() => {
    if (restored.current) {
      return;
    }
    restored.current = true;
    const context = readSessionStorageValue<GoogleResume | null>({
      key: GOOGLE_RESUME_KEY,
      deserialize: deserializeGoogleResume,
    });
    if (context == null || !googleResumeMatches(context, scope, toolkitId)) {
      return;
    }
    active.current = context;
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
    const operation = ++epoch.current;
    setFlow({ type: "VERIFYING" });
    void utils.toolkit.google.review
      .fetch(
        { ...scope, attemptId: context.attemptId },
        { retry: false, staleTime: 0 },
      )
      .then((review) => {
        if (isCurrent(operation)) {
          acceptReview(review);
        }
      })
      .catch(() => {
        if (isCurrent(operation)) {
          setFlow({ type: "ERROR", message: t("verificationFailed") });
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- restore once for the exact mounted management context.
  }, [handle, agentId, toolkitId]);
  const busy =
    flow.type === "AUTHORIZING" ||
    flow.type === "VERIFYING" ||
    flow.type === "CONFIRMING" ||
    cancelling ||
    disconnecting ||
    (flow.type === "UNKNOWN" && flow.checking);
  useEffect(() => {
    pending.current = busy || flow.type === "UNKNOWN";
    onPendingChange?.(pending.current);
    return () => onPendingChange?.(false);
  }, [busy, flow.type, onPendingChange]);
  async function authorize(): Promise<void> {
    if (pending.current || tasks.length === 0) {
      return;
    }
    pending.current = true;
    const operation = ++epoch.current;
    setOperationError(null);
    setAcknowledged(false);
    setFlow({ type: "AUTHORIZING" });
    try {
      const desired = { tasks, timeout };
      const result =
        toolkitId == null
          ? await connect.mutateAsync({ ...scope, desired })
          : await reconnect.mutateAsync({ ...scope, toolkitId, desired });
      const url = new URL(result.authorization_url);
      const state = url.searchParams.get("state");
      if (state == null) {
        throw new Error("Google authorization state is missing.");
      }
      const stateDigest = await googleStateDigest(state);
      if (!isCurrent(operation)) {
        return;
      }
      writeResume({
        ...scope,
        toolkitId,
        attemptId: result.attempt_id,
        expiresAt: result.expires_at,
        stateDigest,
        phase: "AUTHORIZING",
        returnPath: googleReturnPath(scope, toolkitId, props.navigationOrigin),
      });
      window.location.assign(result.authorization_url);
    } catch {
      if (isCurrent(operation)) {
        pending.current = false;
        setFlow({ type: "ERROR", message: t("authorizationFailed") });
      }
    }
  }
  async function publish(): Promise<void> {
    if (
      pending.current ||
      flow.type !== "REVIEW" ||
      active.current == null ||
      !sameGoogleResumeAttempt(readResume(), active.current) ||
      !canPublishGoogleReview(flow.review, tasks, acknowledged, Date.now())
    ) {
      return;
    }
    const review = flow.review;
    const context = active.current;
    pending.current = true;
    const operation = ++epoch.current;
    setOperationError(null);
    setFlow({ type: "CONFIRMING", review });
    writeResume({ ...context, phase: "PUBLISHING" });
    try {
      const settings = { tasks, timeout, security_risk_acknowledged: true };
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
              settings,
            });
      if (isCurrent(operation)) {
        await finish(outcome, context);
      }
    } catch {
      if (isCurrent(operation)) {
        if (!sameGoogleResumeAttempt(readResume(), context)) {
          return;
        }
        writeResume({ ...context, phase: "UNKNOWN" });
        setFlow({ type: "UNKNOWN", checking: false, message: null });
      }
    } finally {
      if (isCurrent(operation)) {
        pending.current = false;
      }
    }
  }
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
      if (isCurrent(operation)) {
        await finish(outcome, context);
      }
    } catch {
      if (isCurrent(operation)) {
        setFlow({
          type: "UNKNOWN",
          checking: false,
          message: t("outcomeUnavailable"),
        });
      }
    }
  }
  const cancelExact = useCallback(async (): Promise<void> => {
    if (pending.current && flow.type !== "UNKNOWN") {
      return;
    }
    if (flow.type === "UNKNOWN" && flow.checking) {
      return;
    }
    const context = active.current;
    const operation = ++epoch.current;
    if (context == null) {
      reset();
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
      if (!isCurrent(operation)) {
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
      }
    } catch {
      if (isCurrent(operation)) {
        setOperationError(t("cancelFailed"));
      }
    } finally {
      if (isCurrent(operation)) {
        setCancelling(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- exact scope cancellation uses refs; candidate changes do not replace parent abandonment handler.
  }, [handle, agentId, flow.type, flow]);
  useEffect(() => {
    onAbandonReady?.(() => {
      void cancelExact();
    });
    return () => onAbandonReady?.(null);
  }, [cancelExact, onAbandonReady]);
  async function disconnectSaved(): Promise<void> {
    if (toolkitId == null || pending.current) {
      return;
    }
    const operation = ++epoch.current;
    setDisconnecting(true);
    setOperationError(null);
    try {
      await disconnect.mutateAsync({ ...scope, toolkitId });
      if (isCurrent(operation)) {
        reset();
        setDisconnectConfirmation(false);
        await invalidate();
      }
    } catch {
      if (isCurrent(operation)) {
        setOperationError(t("disconnectFailed"));
      }
    } finally {
      if (isCurrent(operation)) {
        setDisconnecting(false);
      }
    }
  }
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
  return {
    preparation,
    saved,
    flow,
    tasks,
    timeout,
    metadata,
    acknowledged,
    publishingAllowed:
      flow.type === "REVIEW" &&
      canPublishGoogleReview(flow.review, tasks, acknowledged, Date.now()),
    reconnect: toolkitId != null,
    ownership:
      "owner" in scope ? "user" : scope.agentId != null ? "agent" : "workspace",
    cancelling,
    disconnecting,
    disconnectConfirmation,
    operationError,
    rootRef,
    embedded,
    onTaskChange: (task, selected) => {
      setTasks((current) =>
        selected
          ? Array.from(new Set([...current, task]))
          : current.filter((item) => item !== task),
      );
      setAcknowledged(false);
    },
    onTimeoutChange: setTimeoutValue,
    onMetadataChange: (patch) =>
      setMetadata((current) => ({ ...current, ...patch })),
    onAcknowledgedChange: setAcknowledged,
    onAuthorize: () => {
      setFocusRequest((value) => value + 1);
      void authorize();
    },
    onPublish: () => {
      void publish();
    },
    onCheckOutcome: () => {
      void checkOutcome();
    },
    onCancel: () => {
      void cancelExact();
    },
    onRestart: () => {
      if (!pending.current) {
        void cancelExact();
      }
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
