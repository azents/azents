"use client";

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  RuntimeProviderAuthenticationBindingAuditEventResponse,
  RuntimeProviderAuthenticationBindingResponse,
  RuntimeProviderAuthenticationBindingRotateResponse,
  RuntimeProviderResponse,
} from "@azents/admin-client";

export type RuntimeProviderItem = RuntimeProviderResponse;
export type RuntimeProviderAuthBindingItem =
  RuntimeProviderAuthenticationBindingResponse;
export type RuntimeProviderAuthAuditEvent =
  RuntimeProviderAuthenticationBindingAuditEventResponse;

export type RuntimeProviderListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; items: RuntimeProviderItem[] };

export type RuntimeProviderAuthBindingState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; items: RuntimeProviderAuthBindingItem[] };

export type RuntimeProviderAuthAuditState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      binding: RuntimeProviderAuthBindingItem;
      items: RuntimeProviderAuthAuditEvent[];
    };

export interface RuntimeProvidersPageContentProps {
  state: RuntimeProviderListState;
  selectedProviderId: string | null;
  selectedProvider: RuntimeProviderItem | null;
  authBindingState: RuntimeProviderAuthBindingState;
  authAuditState: RuntimeProviderAuthAuditState;
  authMutating: boolean;
  oneTimeSecret: RuntimeProviderAuthenticationBindingRotateResponse | null;
  updating: boolean;
  errorMessage: string | null;
  onSelectProvider: (providerId: string) => void;
  onToggleEnabled: (provider: RuntimeProviderItem) => void;
  onCreateAuthBinding: () => void;
  onRotateAuthBinding: (binding: RuntimeProviderAuthBindingItem) => void;
  onRevokeAuthBinding: (binding: RuntimeProviderAuthBindingItem) => void;
  onOpenAuthAudit: (binding: RuntimeProviderAuthBindingItem) => void;
  onCloseAuthAudit: () => void;
  onClearOneTimeSecret: () => void;
}

function messageFromUnknown(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Authentication rotation failed";
}

export function useRuntimeProvidersPageContainer(): RuntimeProvidersPageContentProps {
  const utils = trpc.useUtils();
  const providersQuery = trpc.runtimeProvider.list.useQuery();
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(
    null,
  );
  const updatePolicy = trpc.runtimeProvider.updatePolicy.useMutation({
    onSuccess: async () => {
      await utils.runtimeProvider.list.invalidate();
    },
  });

  const items = useMemo(
    () => providersQuery.data?.items ?? [],
    [providersQuery.data?.items],
  );
  const effectiveSelectedProviderId =
    selectedProviderId ?? items[0]?.provider_id ?? null;
  const selectedProvider =
    items.find((item) => item.provider_id === effectiveSelectedProviderId) ??
    null;
  const authBindingsQuery = trpc.runtimeProvider.listAuthBindings.useQuery(
    { providerId: effectiveSelectedProviderId ?? "" },
    { enabled: effectiveSelectedProviderId !== null },
  );
  const [oneTimeSecret, setOneTimeSecret] =
    useState<RuntimeProviderAuthenticationBindingRotateResponse | null>(null);
  const [auditBinding, setAuditBinding] =
    useState<RuntimeProviderAuthBindingItem | null>(null);
  const [rotatePending, setRotatePending] = useState(false);
  const [rotateError, setRotateError] = useState<string | null>(null);
  const authAuditQuery =
    trpc.runtimeProvider.listAuthBindingAuditEvents.useQuery(
      {
        bindingId: auditBinding?.id ?? "",
        offset: 0,
        limit: 50,
      },
      { enabled: auditBinding !== null },
    );
  const invalidateAuthBindings = useCallback(async (): Promise<void> => {
    if (effectiveSelectedProviderId !== null) {
      await utils.runtimeProvider.listAuthBindings.invalidate({
        providerId: effectiveSelectedProviderId,
      });
    }
  }, [effectiveSelectedProviderId, utils.runtimeProvider.listAuthBindings]);
  const createAuthBinding = trpc.runtimeProvider.createAuthBinding.useMutation({
    onSuccess: invalidateAuthBindings,
  });
  const revokeAuthBinding = trpc.runtimeProvider.revokeAuthBinding.useMutation({
    onSuccess: async (binding) => {
      await invalidateAuthBindings();
      if (auditBinding?.id === binding.id) {
        await utils.runtimeProvider.listAuthBindingAuditEvents.invalidate({
          bindingId: binding.id,
          offset: 0,
          limit: 50,
        });
      }
    },
  });
  const state: RuntimeProviderListState = providersQuery.isLoading
    ? { type: "LOADING" }
    : providersQuery.isError
      ? { type: "ERROR", message: providersQuery.error.message }
      : { type: "LOADED", items };
  const authBindingState: RuntimeProviderAuthBindingState =
    effectiveSelectedProviderId === null
      ? { type: "IDLE" }
      : authBindingsQuery.isLoading
        ? { type: "LOADING" }
        : authBindingsQuery.isError
          ? { type: "ERROR", message: authBindingsQuery.error.message }
          : { type: "LOADED", items: authBindingsQuery.data?.items ?? [] };
  const authAuditState: RuntimeProviderAuthAuditState =
    auditBinding === null
      ? { type: "IDLE" }
      : authAuditQuery.isLoading
        ? { type: "LOADING" }
        : authAuditQuery.isError
          ? { type: "ERROR", message: authAuditQuery.error.message }
          : {
              type: "LOADED",
              binding: auditBinding,
              items: authAuditQuery.data?.items ?? [],
            };

  const handleToggleEnabled = useCallback(
    (provider: RuntimeProviderItem): void => {
      updatePolicy.mutate({
        providerId: provider.provider_id,
        enabled: !provider.enabled,
        lifecycleState: provider.lifecycle_state,
        availabilityMode: provider.availability_mode,
      });
    },
    [updatePolicy],
  );
  const handleSelectProvider = useCallback((providerId: string): void => {
    setSelectedProviderId(providerId);
    setAuditBinding(null);
    setRotateError(null);
  }, []);
  const handleCreateAuthBinding = useCallback((): void => {
    if (effectiveSelectedProviderId === null) {
      return;
    }
    createAuthBinding.mutate({
      providerId: effectiveSelectedProviderId,
      subject: `provider:${effectiveSelectedProviderId}:admin`,
    });
  }, [createAuthBinding, effectiveSelectedProviderId]);
  const handleRotateAuthBinding = useCallback(
    (binding: RuntimeProviderAuthBindingItem): void => {
      const rotate = async (): Promise<void> => {
        setRotatePending(true);
        setRotateError(null);
        try {
          const result =
            await utils.client.runtimeProvider.rotateAuthBinding.mutate({
              bindingId: binding.id,
              expectedAdminVersion: binding.admin_version,
              expiresAt: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
            });
          setOneTimeSecret(result);
          await invalidateAuthBindings();
          if (auditBinding?.id === binding.id) {
            await utils.runtimeProvider.listAuthBindingAuditEvents.invalidate({
              bindingId: binding.id,
              offset: 0,
              limit: 50,
            });
          }
        } catch (error) {
          setRotateError(messageFromUnknown(error));
        } finally {
          setRotatePending(false);
        }
      };
      void rotate();
    },
    [
      auditBinding?.id,
      invalidateAuthBindings,
      utils.client.runtimeProvider.rotateAuthBinding,
      utils.runtimeProvider.listAuthBindingAuditEvents,
    ],
  );
  const handleRevokeAuthBinding = useCallback(
    (binding: RuntimeProviderAuthBindingItem): void => {
      if (!window.confirm("Revoke this authentication binding?")) {
        return;
      }
      revokeAuthBinding.mutate({
        bindingId: binding.id,
        expectedAdminVersion: binding.admin_version,
        reason: "Revoked by System Admin",
      });
    },
    [revokeAuthBinding],
  );

  return {
    state,
    selectedProviderId: effectiveSelectedProviderId,
    selectedProvider,
    authBindingState,
    authAuditState,
    authMutating:
      createAuthBinding.isPending ||
      rotatePending ||
      revokeAuthBinding.isPending,
    oneTimeSecret,
    updating: updatePolicy.isPending,
    errorMessage:
      updatePolicy.error?.message ??
      createAuthBinding.error?.message ??
      rotateError ??
      revokeAuthBinding.error?.message ??
      null,
    onSelectProvider: handleSelectProvider,
    onToggleEnabled: handleToggleEnabled,
    onCreateAuthBinding: handleCreateAuthBinding,
    onRotateAuthBinding: handleRotateAuthBinding,
    onRevokeAuthBinding: handleRevokeAuthBinding,
    onOpenAuthAudit: setAuditBinding,
    onCloseAuthAudit: () => setAuditBinding(null),
    onClearOneTimeSecret: () => setOneTimeSecret(null),
  };
}
