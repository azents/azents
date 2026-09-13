"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useElevationModal } from "@/features/security/containers/useElevationModal";
import { trpc } from "@/trpc/client";
import { elevationMethodsOrEmpty } from "../elevation-methods";
import { elevationScreenState, preserveLastSafeOrigin } from "../presentation";
import type {
  AccountLinkFailureReason,
  ExternalAccountCandidate,
  ExternalAccountLinkConfirmationState,
  ExternalAccountLinkOrigin,
} from "../types";

export interface ExternalAccountLinkConfirmationContainerInput {
  originId: string;
}

export interface ExternalAccountLinkConfirmationContainerProps {
  state: ExternalAccountLinkConfirmationState;
  onCreateCandidate: () => void;
  onCheckStatus: () => void;
  onConfirmLink: () => void;
  onStartFresh: () => void;
  onCancel: () => void;
  onSwitchAccount: () => void;
  onReturn: () => void;
  onRetry: () => void;
}

type PendingElevationAction = "create_candidate" | "confirm_candidate";
interface ActiveElevation {
  action: PendingElevationAction;
  generation: number;
}

type ActionState =
  | "IDLE"
  | "CREATING_CANDIDATE"
  | "CHECKING_STATUS"
  | "CONFIRMING_LINK"
  | "CANCELLING"
  | "SWITCHING_ACCOUNT";

function returnToProvider(origin: ExternalAccountLinkOrigin): void {
  if (origin.returnUrl !== null) {
    window.location.assign(origin.returnUrl);
    return;
  }
  window.location.assign("/account/external-accounts");
}

export function useExternalAccountLinkConfirmationContainer({
  originId,
}: ExternalAccountLinkConfirmationContainerInput): ExternalAccountLinkConfirmationContainerProps {
  const router = useRouter();
  const utils = trpc.useUtils();
  const originQuery = trpc.accountLinks.getOrigin.useQuery(
    { originId },
    { retry: false },
  );
  const meQuery = trpc.user.me.useQuery(void 0, { retry: false });
  const [candidate, setCandidate] = useState<ExternalAccountCandidate | null>(
    null,
  );
  const [connected, setConnected] = useState<{
    workspaceName: string;
    provider: "slack" | "discord";
    externalDisplayLabel: string;
  } | null>(null);
  const [action, setAction] = useState<ActionState>("IDLE");
  const [actionError, setActionError] =
    useState<AccountLinkFailureReason | null>(null);
  const [pendingElevation, setPendingElevation] =
    useState<PendingElevationAction | null>(null);
  const activeElevationRef = useRef<ActiveElevation | null>(null);
  const elevationGenerationRef = useRef(0);
  const [scopeUnavailable, setScopeUnavailable] = useState(false);
  const [elevationChallengeKey, setElevationChallengeKey] = useState(0);

  const createMutation = trpc.accountLinks.createCandidate.useMutation();
  const confirmMutation = trpc.accountLinks.confirmCandidate.useMutation();
  const cancelMutation = trpc.accountLinks.cancelCandidate.useMutation();
  const logoutMutation = trpc.auth.logout.useMutation();

  const currentOrigin = useMemo<ExternalAccountLinkOrigin | null>(() => {
    const result = originQuery.data;
    if (result?.type !== "SUCCESS") {
      return null;
    }
    return {
      id: result.data.id,
      workspaceName: result.data.workspace_name,
      workspaceHandle: result.data.workspace_handle,
      provider: result.data.provider,
      providerTeamLabel: result.data.provider_tenant_display_label,
      externalDisplayLabel: result.data.provider_display_label,
      expiresAt: result.data.expires_at,
      state: result.data.state,
      candidateCount: result.data.candidate_count,
      candidateLimit: result.data.candidate_limit,
      returnUrl: result.data.return_context.provider_url,
    };
  }, [originQuery.data]);
  const [lastSafeOrigin, setLastSafeOrigin] =
    useState<ExternalAccountLinkOrigin | null>(null);
  useEffect(() => {
    if (currentOrigin !== null) {
      setLastSafeOrigin(currentOrigin);
    }
  }, [currentOrigin]);
  const origin = preserveLastSafeOrigin(currentOrigin, lastSafeOrigin);

  const beginElevation = useCallback((action: PendingElevationAction): void => {
    const generation = elevationGenerationRef.current + 1;
    elevationGenerationRef.current = generation;
    activeElevationRef.current = { action, generation };
    setElevationChallengeKey(generation);
    setPendingElevation(action);
  }, []);

  const runCreateCandidate = useCallback((): void => {
    setAction("CREATING_CANDIDATE");
    setActionError(null);
    createMutation.mutate(
      { originId },
      {
        onSuccess: (result): void => {
          if (result.type === "SUCCESS") {
            setCandidate({
              id: result.data.id,
              code: result.data.code,
              expiresAt: result.data.expires_at,
              status: result.data.status,
            });
            activeElevationRef.current = null;
            setPendingElevation(null);
            setAction("IDLE");
            return;
          }
          if (result.reason === "elevation_required") {
            beginElevation("create_candidate");
            setAction("IDLE");
            return;
          }
          activeElevationRef.current = null;
          setPendingElevation(null);
          if (result.reason === "unavailable") {
            setScopeUnavailable(true);
            setActionError(null);
            setAction("IDLE");
            return;
          }
          setActionError(result.reason);
          setAction("IDLE");
        },
        onError: (): void => {
          activeElevationRef.current = null;
          setPendingElevation(null);
          setActionError("busy");
          setAction("IDLE");
        },
      },
    );
  }, [beginElevation, createMutation, originId]);

  const runConfirmCandidate = useCallback((): void => {
    if (candidate === null) {
      return;
    }
    setAction("CONFIRMING_LINK");
    setActionError(null);
    confirmMutation.mutate(
      { candidateId: candidate.id },
      {
        onSuccess: (result): void => {
          if (result.type === "SUCCESS") {
            setConnected({
              workspaceName: result.data.workspace_name ?? result.data.provider,
              provider: result.data.provider,
              externalDisplayLabel: result.data.provider_display_label,
            });
            setCandidate(null);
            activeElevationRef.current = null;
            setPendingElevation(null);
            setAction("IDLE");
            void utils.accountLinks.list.invalidate();
            return;
          }
          if (result.reason === "elevation_required") {
            beginElevation("confirm_candidate");
            setAction("IDLE");
            return;
          }
          activeElevationRef.current = null;
          setPendingElevation(null);
          if (result.reason === "unavailable") {
            setScopeUnavailable(true);
            setActionError(null);
            setAction("IDLE");
            return;
          }
          setActionError(result.reason);
          setAction("IDLE");
        },
        onError: (): void => {
          activeElevationRef.current = null;
          setPendingElevation(null);
          setActionError("busy");
          setAction("IDLE");
        },
      },
    );
  }, [beginElevation, candidate, confirmMutation, utils]);

  const onElevated = useCallback((): void => {
    const activeElevation = activeElevationRef.current;
    if (
      activeElevation === null ||
      activeElevation.generation !== elevationChallengeKey
    ) {
      return;
    }
    activeElevationRef.current = null;
    if (activeElevation.action === "create_candidate") {
      runCreateCandidate();
      return;
    }
    runConfirmCandidate();
  }, [elevationChallengeKey, runConfirmCandidate, runCreateCandidate]);

  const elevationMethodsQuery = trpc.security.getElevationMethods.useQuery(
    void 0,
    {
      enabled: pendingElevation !== null,
      retry: false,
    },
  );
  const elevation = useElevationModal(
    elevationMethodsOrEmpty(elevationMethodsQuery.data?.methods),
    onElevated,
    elevationChallengeKey,
  );
  const elevationState = elevationScreenState({
    hasResponse: elevationMethodsQuery.data != null,
    isError: elevationMethodsQuery.isError,
  });

  const onCreateCandidate = useCallback((): void => {
    runCreateCandidate();
  }, [runCreateCandidate]);

  const onCheckStatus = useCallback((): void => {
    if (candidate === null) {
      return;
    }
    setAction("CHECKING_STATUS");
    setActionError(null);
    void utils.accountLinks.getCandidate
      .fetch({ candidateId: candidate.id })
      .then((result): void => {
        if (result.type === "SUCCESS") {
          setCandidate({
            ...candidate,
            status: result.data.status,
            expiresAt: result.data.expires_at,
          });
          setAction("IDLE");
          return;
        }
        if (result.reason === "unavailable") {
          setScopeUnavailable(true);
          setActionError(null);
          setAction("IDLE");
          return;
        }
        setActionError(result.reason);
        if (
          result.reason === "expired" ||
          result.reason === "candidate_terminal" ||
          result.reason === "resource_not_found"
        ) {
          setCandidate({
            ...candidate,
            status: "expired",
          });
        }
        setAction("IDLE");
      })
      .catch((): void => {
        setActionError("busy");
        setAction("IDLE");
      });
  }, [candidate, utils]);

  const onConfirmLink = useCallback((): void => {
    runConfirmCandidate();
  }, [runConfirmCandidate]);

  const cancelCandidateThen = useCallback(
    (next: () => void): void => {
      if (candidate === null) {
        next();
        return;
      }
      setAction("CANCELLING");
      cancelMutation.mutate(
        { candidateId: candidate.id },
        {
          onSuccess: (result): void => {
            if (
              result.type === "SUCCESS" ||
              result.reason === "candidate_terminal" ||
              result.reason === "expired" ||
              result.reason === "resource_not_found"
            ) {
              setCandidate(null);
              setAction("IDLE");
              next();
              return;
            }
            if (result.reason === "unavailable") {
              setCandidate(null);
              setScopeUnavailable(true);
              setAction("IDLE");
              next();
              return;
            }
            setActionError(result.reason);
            setAction("IDLE");
          },
          onError: (): void => {
            setActionError("busy");
            setAction("IDLE");
          },
        },
      );
    },
    [cancelMutation, candidate],
  );

  const onStartFresh = useCallback((): void => {
    cancelCandidateThen((): void => {
      setActionError(null);
      setCandidate(null);
    });
  }, [cancelCandidateThen]);

  const onCancel = useCallback((): void => {
    activeElevationRef.current = null;
    setPendingElevation(null);
    if (origin !== null) {
      cancelCandidateThen((): void => returnToProvider(origin));
    }
  }, [cancelCandidateThen, origin]);

  const onSwitchAccount = useCallback((): void => {
    activeElevationRef.current = null;
    setPendingElevation(null);
    cancelCandidateThen((): void => {
      setAction("SWITCHING_ACCOUNT");
      logoutMutation.mutate(void 0, {
        onSettled: (): void => {
          const next = `/external-channel/link/${encodeURIComponent(originId)}`;
          router.replace(`/login?next=${encodeURIComponent(next)}`);
        },
      });
    });
  }, [cancelCandidateThen, logoutMutation, originId, router]);

  const onReturn = useCallback((): void => {
    if (origin !== null) {
      returnToProvider(origin);
    }
  }, [origin]);

  const onRetry = useCallback((): void => {
    setActionError(null);
    void utils.accountLinks.getOrigin.invalidate({ originId });
    void utils.security.getElevationMethods.invalidate();
    void utils.user.me.invalidate();
  }, [originId, utils]);

  let state: ExternalAccountLinkConfirmationState;
  const originResult = originQuery.data;
  if (originQuery.isLoading || meQuery.isLoading) {
    state = { type: "LOADING" };
  } else if (
    originResult?.type === "FAILURE" &&
    originResult.reason === "resource_not_found"
  ) {
    state = { type: "NOT_FOUND" };
  } else if (
    originResult?.type === "FAILURE" &&
    originResult.reason === "expired"
  ) {
    state =
      origin !== null && meQuery.data != null
        ? {
            type: "ORIGIN_UNAVAILABLE",
            reason: "expired",
            origin,
            accountEmail: meQuery.data.email,
          }
        : { type: "ORIGIN_EXPIRED" };
  } else if (originQuery.isError || meQuery.isError) {
    state = {
      type: "ERROR",
      message: originQuery.error?.message ?? meQuery.error?.message ?? "",
    };
  } else if (origin === null || meQuery.data == null) {
    state = { type: "NOT_FOUND" };
  } else if (connected !== null) {
    state = {
      type: "CONNECTED",
      origin,
      accountEmail: meQuery.data.email,
      workspaceName: connected.workspaceName,
      provider: connected.provider,
      externalDisplayLabel: connected.externalDisplayLabel,
      returnUrl: origin.returnUrl,
    };
  } else if (scopeUnavailable) {
    state = {
      type: "ORIGIN_UNAVAILABLE",
      reason: "unavailable",
      origin,
      accountEmail: meQuery.data.email,
    };
  } else if (origin.state !== "open") {
    state = {
      type: "ORIGIN_UNAVAILABLE",
      reason: origin.state,
      origin,
      accountEmail: meQuery.data.email,
    };
  } else if (pendingElevation !== null) {
    state =
      elevationState === "loading"
        ? {
            type: "ELEVATION_LOADING",
            origin,
            accountEmail: meQuery.data.email,
            action: pendingElevation,
          }
        : elevationState === "error"
          ? {
              type: "ELEVATION_ERROR",
              origin,
              accountEmail: meQuery.data.email,
              action: pendingElevation,
              message:
                elevationMethodsQuery.error?.message ??
                "Verification methods are unavailable.",
            }
          : {
              type: "ELEVATION_REQUIRED",
              origin,
              accountEmail: meQuery.data.email,
              action: pendingElevation,
              elevation,
            };
  } else {
    state = {
      type: "READY",
      origin,
      accountEmail: meQuery.data.email,
      candidate,
      action:
        action === "IDLE"
          ? { type: "IDLE", error: actionError }
          : { type: action },
    };
  }

  return {
    state,
    onCreateCandidate,
    onCheckStatus,
    onConfirmLink,
    onStartFresh,
    onCancel,
    onSwitchAccount,
    onReturn,
    onRetry,
  };
}
