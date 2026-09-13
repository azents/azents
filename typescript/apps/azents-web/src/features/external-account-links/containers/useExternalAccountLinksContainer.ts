"use client";

import { useCallback, useMemo, useState } from "react";
import { useElevationModal } from "@/features/security/containers/useElevationModal";
import { trpc } from "@/trpc/client";
import { elevationMethodsOrEmpty } from "../elevation-methods";
import { elevationScreenState } from "../presentation";
import type {
  AccountLinkFailureReason,
  ExternalAccountLinkItem,
  ExternalAccountLinksState,
} from "../types";
import type { GlobalAccountLinkResponse } from "@azents/public-client";

export interface ExternalAccountLinksContainerProps {
  state: ExternalAccountLinksState;
  onRequestDisconnect: (link: ExternalAccountLinkItem) => void;
  onCancelDisconnect: () => void;
  onConfirmDisconnect: () => void;
  onRetry: () => void;
}

function linkItem(item: GlobalAccountLinkResponse): ExternalAccountLinkItem {
  const accountContext = item.provider_tenant_display_label ?? item.provider;
  return {
    id: item.id,
    accountContextLabel: accountContext,
    provider: item.provider,
    providerTeamLabel: accountContext,
    externalDisplayLabel: item.provider_display_label,
    linkedAt: item.linked_at,
    status: "active",
  };
}

export function useExternalAccountLinksContainer(): ExternalAccountLinksContainerProps {
  const utils = trpc.useUtils();
  const query = trpc.accountLinks.list.useQuery(void 0, { retry: false });
  const [disconnectTarget, setDisconnectTarget] =
    useState<ExternalAccountLinkItem | null>(null);
  const [disconnectError, setDisconnectError] =
    useState<AccountLinkFailureReason | null>(null);
  const [elevationTarget, setElevationTarget] =
    useState<ExternalAccountLinkItem | null>(null);
  const [elevationChallengeKey, setElevationChallengeKey] = useState(0);

  const unlinkMutation = trpc.accountLinks.unlink.useMutation();

  const executeUnlink = useCallback(
    (link: ExternalAccountLinkItem): void => {
      setDisconnectError(null);
      unlinkMutation.mutate(
        { linkId: link.id },
        {
          onSuccess: (result): void => {
            if (result.type === "SUCCESS") {
              setDisconnectTarget(null);
              setElevationTarget(null);
              void utils.accountLinks.list.invalidate();
              return;
            }
            if (result.reason === "elevation_required") {
              setElevationChallengeKey((value) => value + 1);
              setElevationTarget(link);
              return;
            }
            setElevationTarget(null);
            setDisconnectTarget(link);
            setDisconnectError(result.reason);
          },
          onError: (): void => {
            setElevationTarget(null);
            setDisconnectTarget(link);
            setDisconnectError("busy");
          },
        },
      );
    },
    [unlinkMutation, utils],
  );

  const onElevated = useCallback((): void => {
    if (elevationTarget !== null) {
      executeUnlink(elevationTarget);
    }
  }, [elevationTarget, executeUnlink]);

  const elevationMethodsQuery = trpc.security.getElevationMethods.useQuery(
    void 0,
    {
      enabled: elevationTarget !== null,
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

  const links = useMemo(
    () => query.data?.items.map(linkItem) ?? [],
    [query.data?.items],
  );

  const state: ExternalAccountLinksState =
    elevationTarget !== null
      ? elevationState === "loading"
        ? { type: "ELEVATION_LOADING", link: elevationTarget }
        : elevationState === "error"
          ? {
              type: "ELEVATION_ERROR",
              link: elevationTarget,
              message:
                elevationMethodsQuery.error?.message ??
                "Verification methods are unavailable.",
            }
          : {
              type: "ELEVATION_REQUIRED",
              link: elevationTarget,
              elevation,
            }
      : query.isLoading
        ? { type: "LOADING" }
        : query.isError
          ? { type: "ERROR", message: query.error.message }
          : {
              type: "READY",
              links,
              disconnect:
                disconnectTarget === null
                  ? { type: "IDLE" }
                  : unlinkMutation.isPending
                    ? { type: "SUBMITTING", link: disconnectTarget }
                    : {
                        type: "CONFIRMING",
                        link: disconnectTarget,
                        error: disconnectError,
                      },
            };

  const onRequestDisconnect = useCallback(
    (link: ExternalAccountLinkItem): void => {
      setDisconnectError(null);
      setDisconnectTarget(link);
    },
    [],
  );
  const onCancelDisconnect = useCallback((): void => {
    setDisconnectError(null);
    setDisconnectTarget(null);
  }, []);
  const onConfirmDisconnect = useCallback((): void => {
    if (disconnectTarget !== null) {
      executeUnlink(disconnectTarget);
    }
  }, [disconnectTarget, executeUnlink]);
  const onRetry = useCallback((): void => {
    void utils.accountLinks.list.invalidate();
    void utils.security.getElevationMethods.invalidate();
  }, [utils]);

  return {
    state,
    onRequestDisconnect,
    onCancelDisconnect,
    onConfirmDisconnect,
    onRetry,
  };
}
