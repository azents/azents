"use client";

import { useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  externalChannelSettingsInvalidationPlan,
  type ExternalChannelSettingsMutation,
} from "../invalidation";
import type {
  ConnectionDialogState,
  ExternalChannelManagementState,
  ManifestGuidanceState,
  SlackCredentialDraft,
} from "../types";
import type {
  AgentResponse,
  ExternalChannelTransport,
  ManagedBlock,
  ManagedConnection,
  ManagedGrant,
} from "@azents/public-client";

export interface ExternalChannelSettingsContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface ExternalChannelSettingsContainerOutput {
  handle: string;
  agent: AgentResponse;
  state: ExternalChannelManagementState;
  manifestState: ManifestGuidanceState;
  dialogState: ConnectionDialogState;
  actionError: string | null;
  actionTarget: string | null;
  actionsBusy: boolean;
  onOpenSetup: () => void;
  onOpenEdit: (connection: ManagedConnection) => void;
  onCloseDialog: () => void;
  onDialogChange: (state: Exclude<ConnectionDialogState, null>) => void;
  onSubmitDialog: () => void;
  onValidate: (connection: ManagedConnection) => void;
  onDisconnect: (connection: ManagedConnection) => void;
  onRevokeGrant: (grant: ManagedGrant) => void;
  onRemoveBlock: (block: ManagedBlock) => void;
}

const EMPTY_CREDENTIALS: SlackCredentialDraft = {
  botToken: "",
  signingSecret: "",
  appToken: "",
};

function normalizeError(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function useExternalChannelSettingsContainer({
  handle,
  agent,
}: ExternalChannelSettingsContainerProps): ExternalChannelSettingsContainerOutput {
  const utils = trpc.useUtils();
  const [manifestTransport, setManifestTransport] =
    useState<ExternalChannelTransport>("http");
  const [dialogState, setDialogState] = useState<ConnectionDialogState>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionTarget, setActionTarget] = useState<string | null>(null);
  const actionLock = useRef(false);
  const queryInput = { handle, agentId: agent.id };

  const connectionsQuery =
    trpc.externalChannel.listConnections.useQuery(queryInput);
  const accessQuery = trpc.externalChannel.listAgentAccess.useQuery(queryInput);
  const manifestQuery = trpc.externalChannel.getManifestGuidance.useQuery(
    {
      ...queryInput,
      appName: agent.name,
      transport: manifestTransport,
    },
    {
      enabled: dialogState !== null,
    },
  );

  const clearAction = (): void => {
    actionLock.current = false;
    setActionError(null);
    setActionTarget(null);
  };
  const beginAction = (target: string): boolean => {
    if (actionLock.current) {
      return false;
    }
    actionLock.current = true;
    setActionError(null);
    setActionTarget(target);
    return true;
  };
  const failAction = (error: unknown): void => {
    actionLock.current = false;
    setActionError(normalizeError(error));
    setActionTarget(null);
  };

  const invalidate = async (
    mutation: ExternalChannelSettingsMutation,
  ): Promise<void> => {
    await Promise.all(
      externalChannelSettingsInvalidationPlan(mutation).map((target) => {
        switch (target) {
          case "connections":
            return utils.externalChannel.listConnections.invalidate(queryInput);
          case "agentAccess":
            return utils.externalChannel.listAgentAccess.invalidate(queryInput);
          case "sessionChannels":
            return utils.externalChannel.listSessionChannels.invalidate();
        }
      }),
    );
  };

  const setupMutation = trpc.externalChannel.setupSlackConnection.useMutation({
    onSuccess: async () => {
      setDialogState(null);
      try {
        await invalidate("setup");
      } finally {
        clearAction();
      }
    },
    onError: (error) => failAction(error),
  });
  const validateMutation = trpc.externalChannel.validateConnection.useMutation({
    onSuccess: async () => {
      try {
        await invalidate("validate");
      } finally {
        clearAction();
      }
    },
    onError: (error) => failAction(error),
  });
  const updateMutation = trpc.externalChannel.updateSlackConnection.useMutation(
    {
      onSuccess: async () => {
        setDialogState(null);
        try {
          await invalidate("update");
        } finally {
          clearAction();
        }
      },
      onError: (error) => failAction(error),
    },
  );
  const disconnectMutation =
    trpc.externalChannel.disconnectConnection.useMutation({
      onSuccess: async () => {
        try {
          await invalidate("disconnect");
        } finally {
          clearAction();
        }
      },
      onError: (error) => failAction(error),
    });
  const revokeMutation = trpc.externalChannel.revokeAccessGrant.useMutation({
    onSuccess: async () => {
      try {
        await invalidate("revokeGrant");
      } finally {
        clearAction();
      }
    },
    onError: (error) => failAction(error),
  });
  const removeBlockMutation =
    trpc.externalChannel.removeAccessBlock.useMutation({
      onSuccess: async () => {
        try {
          await invalidate("removeBlock");
        } finally {
          clearAction();
        }
      },
      onError: (error) => failAction(error),
    });

  const state: ExternalChannelManagementState =
    connectionsQuery.isPending || accessQuery.isPending
      ? { type: "LOADING" }
      : connectionsQuery.isError
        ? { type: "ERROR", message: connectionsQuery.error.message }
        : accessQuery.isError
          ? { type: "ERROR", message: accessQuery.error.message }
          : {
              type: "LOADED",
              connections: connectionsQuery.data.items,
              grants: accessQuery.data.grants,
              blocks: accessQuery.data.blocks,
            };
  const manifestState: ManifestGuidanceState =
    dialogState === null
      ? { type: "IDLE" }
      : manifestQuery.isPending
        ? { type: "LOADING" }
        : manifestQuery.isError
          ? { type: "ERROR", message: manifestQuery.error.message }
          : { type: "LOADED", manifest: manifestQuery.data };

  return {
    handle,
    agent,
    state,
    manifestState,
    dialogState,
    actionError,
    actionTarget,
    actionsBusy: actionTarget !== null,
    onOpenSetup: () => {
      if (actionLock.current) {
        return;
      }
      setActionError(null);
      setManifestTransport("http");
      setDialogState({
        type: "SETUP",
        appId: "",
        transport: "http",
        credentials: { ...EMPTY_CREDENTIALS },
      });
    },
    onOpenEdit: (connection) => {
      if (actionLock.current) {
        return;
      }
      setActionError(null);
      setManifestTransport(connection.transport);
      setDialogState({
        type: "EDIT",
        connectionId: connection.id,
        appId: connection.provider_app_id ?? "",
        transport: connection.transport,
        credentials: { ...EMPTY_CREDENTIALS },
      });
    },
    onCloseDialog: () => {
      setDialogState(null);
      setActionError(null);
    },
    onDialogChange: (nextState) => {
      setDialogState(nextState);
      if (nextState.transport !== manifestTransport) {
        setManifestTransport(nextState.transport);
      }
    },
    onSubmitDialog: () => {
      if (dialogState === null) {
        return;
      }
      if (!beginAction("dialog")) {
        return;
      }
      const credentials = {
        botToken: dialogState.credentials.botToken,
        signingSecret: dialogState.credentials.signingSecret,
        appToken:
          dialogState.credentials.appToken.trim() === ""
            ? null
            : dialogState.credentials.appToken,
      };
      if (dialogState.type === "SETUP") {
        setupMutation.mutate({
          ...queryInput,
          appId: dialogState.appId,
          transport: dialogState.transport,
          credentials,
        });
        return;
      }
      updateMutation.mutate({
        ...queryInput,
        connectionId: dialogState.connectionId,
        appId: dialogState.appId,
        transport: dialogState.transport,
        credentials,
      });
    },
    onValidate: (connection) => {
      if (!beginAction(connection.id)) {
        return;
      }
      validateMutation.mutate({
        ...queryInput,
        connectionId: connection.id,
      });
    },
    onDisconnect: (connection) => {
      if (!beginAction(connection.id)) {
        return;
      }
      disconnectMutation.mutate({
        ...queryInput,
        connectionId: connection.id,
      });
    },
    onRevokeGrant: (grant) => {
      if (!beginAction(grant.id)) {
        return;
      }
      revokeMutation.mutate({ ...queryInput, grantId: grant.id });
    },
    onRemoveBlock: (block) => {
      if (!beginAction(block.id)) {
        return;
      }
      removeBlockMutation.mutate({ ...queryInput, blockId: block.id });
    },
  };
}
