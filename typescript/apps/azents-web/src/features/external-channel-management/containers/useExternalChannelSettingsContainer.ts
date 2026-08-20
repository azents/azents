"use client";

import { useRef, useState } from "react";
import {
  DEFAULT_DISCORD_THREAD_AUTO_ARCHIVE_DURATION,
  discordThreadAutoArchiveDurationFromConfiguration,
} from "@/shared/lib/discord-thread-auto-archive-duration";
import { trpc } from "@/trpc/client";
import {
  externalChannelSettingsInvalidationPlan,
  type ExternalChannelSettingsMutation,
} from "../invalidation";
import type {
  ConnectionDialogState,
  DiscordConnectionDialogState,
  ExternalChannelManagementState,
  ManifestGuidanceState,
  SlackCredentialDraft,
} from "../types";
import type {
  AgentResponse,
  DiscordThreadAutoArchiveDurationMinutes,
  ExternalChannelConnectionStatusSnapshot,
  ExternalChannelResponseMode,
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
  discordDialogState: DiscordConnectionDialogState;
  actionError: string | null;
  actionTarget: string | null;
  actionsBusy: boolean;
  discordThreadDurationDrafts: Record<
    string,
    DiscordThreadAutoArchiveDurationMinutes
  >;
  discordThreadDurationSavedConnectionId: string | null;
  defaultResponseMode: ExternalChannelResponseMode;
  defaultResponseModeDraft: ExternalChannelResponseMode;
  defaultResponseModeSaving: boolean;
  defaultResponseModeError: string | null;
  defaultResponseModeSaved: boolean;
  canManageWorkspaceMultiApps: boolean;
  onDefaultResponseModeChange: (mode: ExternalChannelResponseMode) => void;
  onSaveDefaultResponseMode: () => void;
  onOpenSetup: () => void;
  onOpenDiscordSetup: () => void;
  onOpenEdit: (connection: ManagedConnection) => void;
  onCloseDialog: () => void;
  onDialogChange: (state: Exclude<ConnectionDialogState, null>) => void;
  onSubmitDialog: () => void;
  onCloseDiscordDialog: () => void;
  onDiscordDialogChange: (
    state: Exclude<DiscordConnectionDialogState, null>,
  ) => void;
  onSubmitDiscordDialog: () => void;
  onValidate: (connection: ManagedConnection) => void;
  onDisconnect: (connection: ManagedConnection) => void;
  onUpdateAccessPolicy: (
    connection: ManagedConnection,
    openAccessEnabled: boolean,
  ) => void;
  onDiscordThreadDurationChange: (
    connectionId: string,
    duration: DiscordThreadAutoArchiveDurationMinutes,
  ) => void;
  onSaveDiscordThreadDuration: (connection: ManagedConnection) => void;
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

function validationMessage(
  result: ExternalChannelConnectionStatusSnapshot,
): string | null {
  if (result.status === "active") {
    return null;
  }
  return [result.message, result.action_hint]
    .filter((value): value is string => value !== null && value !== "")
    .join(" ");
}

export function useExternalChannelSettingsContainer({
  handle,
  agent,
}: ExternalChannelSettingsContainerProps): ExternalChannelSettingsContainerOutput {
  const utils = trpc.useUtils();
  const [manifestTransport, setManifestTransport] =
    useState<ExternalChannelTransport>("http");
  const [dialogState, setDialogState] = useState<ConnectionDialogState>(null);
  const [discordDialogState, setDiscordDialogState] =
    useState<DiscordConnectionDialogState>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionTarget, setActionTarget] = useState<string | null>(null);
  const [discordThreadDurationDrafts, setDiscordThreadDurationDrafts] =
    useState<Record<string, DiscordThreadAutoArchiveDurationMinutes>>({});
  const [
    discordThreadDurationSavedConnectionId,
    setDiscordThreadDurationSavedConnectionId,
  ] = useState<string | null>(null);
  const [defaultResponseModeDraft, setDefaultResponseModeDraft] =
    useState<ExternalChannelResponseMode | null>(null);
  const [defaultResponseModeError, setDefaultResponseModeError] = useState<
    string | null
  >(null);
  const [defaultResponseModeSaved, setDefaultResponseModeSaved] =
    useState(false);
  const actionLock = useRef(false);
  const queryInput = { handle, agentId: agent.id };

  const connectionsQuery =
    trpc.externalChannel.listConnections.useQuery(queryInput);
  const accessQuery = trpc.externalChannel.listAgentAccess.useQuery(queryInput);
  const workspaceMemberQuery = trpc.workspaceMember.me.useQuery({ handle });
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
    setDiscordThreadDurationSavedConnectionId(null);
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
  const setupDiscordMutation =
    trpc.externalChannel.setupDiscordConnection.useMutation({
      onSuccess: async () => {
        setDiscordDialogState(null);
        try {
          await invalidate("setup");
        } finally {
          clearAction();
        }
      },
      onError: (error) => failAction(error),
    });
  const validateMutation = trpc.externalChannel.validateConnection.useMutation({
    onSuccess: async (result) => {
      try {
        await invalidate("validate");
      } finally {
        actionLock.current = false;
        setActionTarget(null);
        setActionError(validationMessage(result));
      }
    },
    onError: (error) => failAction(error),
  });
  const updateMutation = trpc.externalChannel.updateSlackConnection.useMutation(
    {
      onSuccess: async (result) => {
        setDialogState(null);
        try {
          await invalidate("update");
        } finally {
          actionLock.current = false;
          setActionTarget(null);
          setActionError(validationMessage(result));
        }
      },
      onError: (error) => failAction(error),
    },
  );
  const updateDiscordMutation =
    trpc.externalChannel.updateDiscordConnection.useMutation({
      onSuccess: async (result) => {
        setDiscordDialogState(null);
        try {
          await invalidate("update");
        } finally {
          actionLock.current = false;
          setActionTarget(null);
          setActionError(validationMessage(result));
        }
      },
      onError: (error) => failAction(error),
    });
  const discordThreadDurationMutation =
    trpc.externalChannel.setDiscordThreadDuration.useMutation({
      onSuccess: async (_, variables) => {
        try {
          await invalidate("update");
          setDiscordThreadDurationSavedConnectionId(variables.connectionId);
        } finally {
          clearAction();
        }
      },
      onError: (error) => failAction(error),
    });
  const accessPolicyMutation =
    trpc.externalChannel.updateConnectionAccessPolicy.useMutation({
      onSuccess: async () => {
        try {
          await invalidate("update");
        } finally {
          clearAction();
        }
      },
      onError: (error) => failAction(error),
    });
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
  const defaultResponseModeMutation =
    trpc.externalChannel.updateDefaultResponseMode.useMutation({
      onSuccess: async () => {
        try {
          await utils.externalChannel.listConnections.invalidate(queryInput);
          setDefaultResponseModeDraft(null);
          setDefaultResponseModeError(null);
          setDefaultResponseModeSaved(true);
        } catch (error) {
          setDefaultResponseModeError(normalizeError(error));
        }
      },
      onError: (error) => {
        setDefaultResponseModeError(normalizeError(error));
        setDefaultResponseModeSaved(false);
      },
    });

  const defaultResponseMode =
    connectionsQuery.data?.default_response_mode ?? "all_messages";
  const effectiveDefaultResponseMode =
    defaultResponseModeDraft ?? defaultResponseMode;

  const state: ExternalChannelManagementState =
    connectionsQuery.isPending || accessQuery.isPending
      ? { type: "LOADING" }
      : connectionsQuery.isError
        ? { type: "ERROR", message: connectionsQuery.error.message }
        : accessQuery.isError
          ? { type: "ERROR", message: accessQuery.error.message }
          : {
              type: "LOADED",
              defaultResponseMode: connectionsQuery.data.default_response_mode,
              connections: connectionsQuery.data.items,
              associatedMultiApps: connectionsQuery.data.associated_multi_apps,
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
    discordDialogState,
    actionError,
    actionTarget,
    actionsBusy: actionTarget !== null,
    discordThreadDurationDrafts,
    discordThreadDurationSavedConnectionId,
    defaultResponseMode,
    defaultResponseModeDraft: effectiveDefaultResponseMode,
    defaultResponseModeSaving: defaultResponseModeMutation.isPending,
    defaultResponseModeError,
    defaultResponseModeSaved,
    canManageWorkspaceMultiApps:
      workspaceMemberQuery.data?.role === "owner" ||
      workspaceMemberQuery.data?.role === "manager",
    onDefaultResponseModeChange: (mode) => {
      setDefaultResponseModeDraft(mode);
      setDefaultResponseModeError(null);
      setDefaultResponseModeSaved(false);
    },
    onSaveDefaultResponseMode: () => {
      if (
        defaultResponseModeMutation.isPending ||
        effectiveDefaultResponseMode === defaultResponseMode
      ) {
        return;
      }
      setDefaultResponseModeError(null);
      setDefaultResponseModeSaved(false);
      defaultResponseModeMutation.mutate({
        ...queryInput,
        responseMode: effectiveDefaultResponseMode,
      });
    },
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
    onOpenDiscordSetup: () => {
      if (actionLock.current) {
        return;
      }
      setActionError(null);
      setDiscordDialogState({
        type: "SETUP",
        appId: "",
        targetGuildId: "",
        threadAutoArchiveDurationMinutes:
          DEFAULT_DISCORD_THREAD_AUTO_ARCHIVE_DURATION,
        botToken: "",
      });
    },
    onOpenEdit: (connection) => {
      if (actionLock.current) {
        return;
      }
      setActionError(null);
      if (connection.provider === "discord") {
        setDiscordDialogState({
          type: "EDIT",
          connectionId: connection.id,
          appId: connection.provider_app_id ?? "",
          targetGuildId:
            typeof connection.provider_config?.target_guild_id === "string"
              ? connection.provider_config.target_guild_id
              : "",
          threadAutoArchiveDurationMinutes:
            discordThreadAutoArchiveDurationFromConfiguration(
              connection.provider_config,
            ),
          botToken: "",
        });
        return;
      }
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
    onCloseDiscordDialog: () => {
      setDiscordDialogState(null);
      setActionError(null);
    },
    onDiscordDialogChange: (nextState) => {
      setDiscordDialogState(nextState);
    },
    onSubmitDiscordDialog: () => {
      if (discordDialogState === null || !beginAction("discord-dialog")) {
        return;
      }
      const credentials = {
        botToken: discordDialogState.botToken,
        targetGuildId: discordDialogState.targetGuildId,
      };
      if (discordDialogState.type === "SETUP") {
        setupDiscordMutation.mutate({
          ...queryInput,
          appId: discordDialogState.appId,
          credentials,
          threadAutoArchiveDurationMinutes:
            discordDialogState.threadAutoArchiveDurationMinutes,
        });
        return;
      }
      updateDiscordMutation.mutate({
        ...queryInput,
        connectionId: discordDialogState.connectionId,
        appId: discordDialogState.appId,
        credentials,
        threadAutoArchiveDurationMinutes:
          discordDialogState.threadAutoArchiveDurationMinutes,
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
    onUpdateAccessPolicy: (connection, openAccessEnabled) => {
      if (!beginAction(connection.id)) {
        return;
      }
      accessPolicyMutation.mutate({
        ...queryInput,
        connectionId: connection.id,
        openAccessEnabled,
      });
    },
    onDiscordThreadDurationChange: (connectionId, duration) => {
      setDiscordThreadDurationDrafts((current) => ({
        ...current,
        [connectionId]: duration,
      }));
      setDiscordThreadDurationSavedConnectionId(null);
    },
    onSaveDiscordThreadDuration: (connection) => {
      const duration =
        discordThreadDurationDrafts[connection.id] ??
        discordThreadAutoArchiveDurationFromConfiguration(
          connection.provider_config,
        );
      if (!beginAction(connection.id)) {
        return;
      }
      discordThreadDurationMutation.mutate({
        ...queryInput,
        connectionId: connection.id,
        threadAutoArchiveDurationMinutes: duration,
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
