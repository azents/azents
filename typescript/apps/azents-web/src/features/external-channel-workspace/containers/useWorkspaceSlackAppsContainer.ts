"use client";

import { useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  DiscordMultiConnectionDraft,
  MultiConnectionDraft,
  SlackManagementHandoffState,
  WorkspaceMultiAppsState,
} from "../types";
import type {
  ExternalChannelMultiConnectionImpact,
  ExternalChannelMultiRouteImpact,
  ManagedChannelDefault,
  ManagedMultiConnection,
  ManagedMultiRoute,
} from "@azents/public-client";

const PAGE_SIZE = 50;
const EMPTY_DRAFT: MultiConnectionDraft = {
  appId: "",
  transport: "http",
  credentials: { botToken: "", signingSecret: "", appToken: "" },
};
const EMPTY_DISCORD_DRAFT: DiscordMultiConnectionDraft = {
  appId: "",
  targetGuildId: "",
  botToken: "",
};

export interface WorkspaceSlackAppsContainerProps {
  handle: string;
  initialConnectionId: string | null;
  interactionId: string | null;
}

export interface WorkspaceSlackAppsContainerOutput {
  handle: string;
  state: WorkspaceMultiAppsState;
  connectionOffset: number;
  selectedConnectionId: string | null;
  selectedConnection: ManagedMultiConnection | null;
  routeItems: ManagedMultiRoute[];
  defaultItems: ManagedChannelDefault[];
  routeOffset: number;
  defaultOffset: number;
  routeImpact: ExternalChannelMultiRouteImpact | null;
  connectionImpact: ExternalChannelMultiConnectionImpact | null;
  previewRouteId: string | null;
  previewDisconnect: boolean;
  setupDraft: MultiConnectionDraft;
  editDraft: MultiConnectionDraft;
  discordSetupDraft: DiscordMultiConnectionDraft;
  discordEditDraft: DiscordMultiConnectionDraft;
  agentId: string;
  providerChannelId: string;
  defaultRouteId: string;
  focusedHandoff: boolean;
  handoffState: SlackManagementHandoffState;
  busy: boolean;
  actionError: string | null;
  detailError: string | null;
  routeImpactError: string | null;
  connectionImpactError: string | null;
  connectionLoading: boolean;
  routesLoading: boolean;
  defaultsLoading: boolean;
  routeImpactLoading: boolean;
  connectionImpactLoading: boolean;
  canManage: boolean;
  onSelectConnection: (connectionId: string) => void;
  onSetupDraftChange: (draft: MultiConnectionDraft) => void;
  onEditDraftChange: (draft: MultiConnectionDraft) => void;
  onDiscordSetupDraftChange: (draft: DiscordMultiConnectionDraft) => void;
  onDiscordEditDraftChange: (draft: DiscordMultiConnectionDraft) => void;
  onAgentIdChange: (agentId: string) => void;
  onProviderChannelIdChange: (channelId: string) => void;
  onDefaultRouteIdChange: (routeId: string) => void;
  onCreate: () => void;
  onSaveConnection: () => void;
  onCreateDiscord: () => void;
  onSaveDiscordConnection: () => void;
  onValidate: () => void;
  onPreviewRouteRemoval: (routeId: string) => void;
  onRemoveRoute: () => void;
  onReenableRoute: (routeId: string) => void;
  onAddRoute: () => void;
  onSetDefault: () => void;
  onClearDefault: (providerChannelId: string) => void;
  onPreviewDisconnect: () => void;
  onDisconnect: () => void;
  onCancelPreview: () => void;
  onConnectionPage: (offset: number) => void;
  onRoutePage: (offset: number) => void;
  onDefaultPage: (offset: number) => void;
  onRetryRouteImpact: () => void;
  onRetryConnectionImpact: () => void;
}

function errorCode(error: unknown): string | null {
  if (typeof error !== "object" || error === null || !("data" in error)) {
    return null;
  }
  const data = error.data;
  if (typeof data !== "object" || data === null || !("code" in data)) {
    return null;
  }
  return typeof data.code === "string" ? data.code : null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function useWorkspaceSlackAppsContainer({
  handle,
  initialConnectionId,
  interactionId,
}: WorkspaceSlackAppsContainerProps): WorkspaceSlackAppsContainerOutput {
  const utils = trpc.useUtils();
  const [selectedConnectionId, setSelectedConnectionId] = useState<
    string | null
  >(initialConnectionId ?? null);
  const [connectionOffset, setConnectionOffset] = useState(0);
  const [routeOffset, setRouteOffset] = useState(0);
  const [defaultOffset, setDefaultOffset] = useState(0);
  const [setupDraft, setSetupDraft] =
    useState<MultiConnectionDraft>(EMPTY_DRAFT);
  const [editDraft, setEditDraft] = useState<MultiConnectionDraft>(EMPTY_DRAFT);
  const [discordSetupDraft, setDiscordSetupDraft] =
    useState<DiscordMultiConnectionDraft>(EMPTY_DISCORD_DRAFT);
  const [discordEditDraft, setDiscordEditDraft] =
    useState<DiscordMultiConnectionDraft>(EMPTY_DISCORD_DRAFT);
  const [agentId, setAgentId] = useState("");
  const [providerChannelId, setProviderChannelId] = useState("");
  const [defaultRouteId, setDefaultRouteId] = useState("");
  const [previewRouteId, setPreviewRouteId] = useState<string | null>(null);
  const [previewDisconnect, setPreviewDisconnect] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const meQuery = trpc.workspaceMember.me.useQuery({ handle });
  const listQuery = trpc.externalChannel.listMultiConnections.useQuery({
    handle,
    offset: connectionOffset,
    limit: PAGE_SIZE,
  });
  const canManage =
    meQuery.data?.role === "owner" || meQuery.data?.role === "manager";

  useEffect((): void => {
    if (selectedConnectionId !== null || listQuery.data?.items.length === 0) {
      return;
    }
    setSelectedConnectionId(
      (connectionOffset === 0 ? initialConnectionId : null) ??
        listQuery.data?.items[0]?.id ??
        null,
    );
  }, [
    connectionOffset,
    initialConnectionId,
    listQuery.data?.items,
    selectedConnectionId,
  ]);

  const detailQuery = trpc.externalChannel.getMultiConnection.useQuery(
    { handle, connectionId: selectedConnectionId ?? "missing" },
    { enabled: selectedConnectionId !== null },
  );
  const routesQuery = trpc.externalChannel.listMultiRoutes.useQuery(
    {
      handle,
      connectionId: selectedConnectionId ?? "missing",
      offset: routeOffset,
      limit: PAGE_SIZE,
    },
    { enabled: selectedConnectionId !== null },
  );
  const defaultsQuery = trpc.externalChannel.listMultiChannelDefaults.useQuery(
    {
      handle,
      connectionId: selectedConnectionId ?? "missing",
      offset: defaultOffset,
      limit: PAGE_SIZE,
    },
    { enabled: selectedConnectionId !== null },
  );
  const routeImpactQuery = trpc.externalChannel.getMultiRouteImpact.useQuery(
    {
      handle,
      connectionId: selectedConnectionId ?? "missing",
      routeId: previewRouteId ?? "missing",
    },
    { enabled: selectedConnectionId !== null && previewRouteId !== null },
  );
  const connectionImpactQuery =
    trpc.externalChannel.getMultiConnectionImpact.useQuery(
      { handle, connectionId: selectedConnectionId ?? "missing" },
      { enabled: selectedConnectionId !== null && previewDisconnect },
    );
  const handoffQuery = trpc.externalChannel.loadMultiManagementHandoff.useQuery(
    { handle, interactionId: interactionId ?? "missing" },
    { enabled: interactionId !== null },
  );

  useEffect((): void => {
    if (!detailQuery.data) {
      return;
    }
    setEditDraft({
      appId: detailQuery.data.provider_app_id ?? "",
      transport: detailQuery.data.transport,
      credentials: { botToken: "", signingSecret: "", appToken: "" },
    });
  }, [detailQuery.data]);

  useEffect((): void => {
    if (detailQuery.data?.provider !== "discord") {
      return;
    }
    setDiscordEditDraft({
      appId: detailQuery.data.provider_app_id ?? "",
      targetGuildId:
        typeof detailQuery.data.provider_config?.target_guild_id === "string"
          ? detailQuery.data.provider_config.target_guild_id
          : "",
      botToken: "",
    });
  }, [detailQuery.data]);

  useEffect((): void => {
    if (!handoffQuery.data) {
      return;
    }
    setSelectedConnectionId(handoffQuery.data.connection_id);
    setProviderChannelId(handoffQuery.data.provider_channel_id);
  }, [handoffQuery.data]);

  const refresh = async (): Promise<void> => {
    await Promise.all([
      utils.externalChannel.listMultiConnections.invalidate(),
      utils.externalChannel.getMultiConnection.invalidate(),
      utils.externalChannel.listMultiRoutes.invalidate(),
      utils.externalChannel.listMultiChannelDefaults.invalidate(),
      utils.externalChannel.getMultiRouteImpact.invalidate(),
      utils.externalChannel.getMultiConnectionImpact.invalidate(),
    ]);
  };
  const fail = async (error: unknown): Promise<void> => {
    setActionError(errorMessage(error));
    if (errorCode(error) === "CONFLICT") {
      await refresh();
    }
  };
  const createMutation = trpc.externalChannel.setupMultiConnection.useMutation({
    onSuccess: async (result) => {
      setSetupDraft(EMPTY_DRAFT);
      setSelectedConnectionId(result.connection.id);
      await refresh();
    },
    onError: (error) => void fail(error),
  });
  const createDiscordMutation =
    trpc.externalChannel.setupMultiDiscordConnection.useMutation({
      onSuccess: async (result) => {
        setDiscordSetupDraft(EMPTY_DISCORD_DRAFT);
        setSelectedConnectionId(result.connection.id);
        await refresh();
      },
      onError: (error) => void fail(error),
    });
  const updateMutation = trpc.externalChannel.updateMultiConnection.useMutation(
    {
      onSuccess: () => void refresh(),
      onError: (error) => void fail(error),
    },
  );
  const updateDiscordMutation =
    trpc.externalChannel.updateMultiDiscordConnection.useMutation({
      onSuccess: () => void refresh(),
      onError: (error) => void fail(error),
    });
  const validateMutation =
    trpc.externalChannel.validateMultiConnection.useMutation({
      onSuccess: () => void refresh(),
      onError: (error) => void fail(error),
    });
  const addRouteMutation = trpc.externalChannel.addMultiRoute.useMutation({
    onSuccess: () => {
      setAgentId("");
      void refresh();
    },
    onError: (error) => void fail(error),
  });
  const removeRouteMutation = trpc.externalChannel.removeMultiRoute.useMutation(
    {
      onSuccess: () => {
        setDefaultRouteId((current) =>
          current === previewRouteId ? "" : current,
        );
        setPreviewRouteId(null);
        void refresh();
      },
      onError: (error) => void fail(error),
    },
  );
  const reenableRouteMutation =
    trpc.externalChannel.reenableMultiRoute.useMutation({
      onSuccess: () => void refresh(),
      onError: (error) => void fail(error),
    });
  const replaceDefaultMutation =
    trpc.externalChannel.replaceMultiChannelDefault.useMutation({
      onSuccess: () => {
        if (interactionId === null) {
          setProviderChannelId("");
        }
        void refresh();
      },
      onError: (error) => void fail(error),
    });
  const clearDefaultMutation =
    trpc.externalChannel.clearMultiChannelDefault.useMutation({
      onSuccess: () => void refresh(),
      onError: (error) => void fail(error),
    });
  const disconnectMutation =
    trpc.externalChannel.disconnectMultiConnection.useMutation({
      onSuccess: () => {
        setPreviewDisconnect(false);
        void refresh();
      },
      onError: (error) => void fail(error),
    });

  const selectedConnection = detailQuery.data ?? null;
  const detailError =
    detailQuery.error?.message ??
    routesQuery.error?.message ??
    defaultsQuery.error?.message ??
    null;
  const generation = selectedConnection?.generation ?? null;
  const busy =
    createMutation.isPending ||
    createDiscordMutation.isPending ||
    updateMutation.isPending ||
    updateDiscordMutation.isPending ||
    validateMutation.isPending ||
    addRouteMutation.isPending ||
    removeRouteMutation.isPending ||
    reenableRouteMutation.isPending ||
    replaceDefaultMutation.isPending ||
    clearDefaultMutation.isPending ||
    disconnectMutation.isPending;
  const state: WorkspaceMultiAppsState = useMemo(() => {
    if (meQuery.isPending || listQuery.isPending) {
      return { type: "LOADING" };
    }
    if (meQuery.isError && errorCode(meQuery.error) === "FORBIDDEN") {
      return { type: "FORBIDDEN", message: meQuery.error.message };
    }
    if (listQuery.isError && errorCode(listQuery.error) === "FORBIDDEN") {
      return { type: "FORBIDDEN", message: listQuery.error.message };
    }
    if (
      listQuery.isError &&
      errorCode(listQuery.error) === "SERVICE_UNAVAILABLE"
    ) {
      return { type: "UNAVAILABLE", message: listQuery.error.message };
    }
    if (meQuery.isError) {
      return {
        type: "ERROR",
        message: meQuery.error.message,
      };
    }
    if (listQuery.isError) {
      return { type: "ERROR", message: listQuery.error.message };
    }
    return { type: "LOADED", connections: listQuery.data.items };
  }, [listQuery, meQuery]);

  return {
    handle,
    state,
    connectionOffset,
    selectedConnectionId,
    selectedConnection,
    routeItems: routesQuery.data?.items ?? [],
    defaultItems: defaultsQuery.data?.items ?? [],
    routeOffset,
    defaultOffset,
    routeImpact: routeImpactQuery.data ?? null,
    connectionImpact: connectionImpactQuery.data ?? null,
    previewRouteId,
    previewDisconnect,
    setupDraft,
    editDraft,
    discordSetupDraft,
    discordEditDraft,
    agentId,
    providerChannelId,
    defaultRouteId,
    focusedHandoff: interactionId !== null,
    handoffState: {
      handoff: handoffQuery.data ?? null,
      message: handoffQuery.isError ? handoffQuery.error.message : null,
    },
    busy,
    actionError,
    detailError,
    routeImpactError: routeImpactQuery.error?.message ?? null,
    connectionImpactError: connectionImpactQuery.error?.message ?? null,
    connectionLoading: selectedConnectionId !== null && detailQuery.isPending,
    routesLoading: selectedConnectionId !== null && routesQuery.isPending,
    defaultsLoading: selectedConnectionId !== null && defaultsQuery.isPending,
    routeImpactLoading: previewRouteId !== null && routeImpactQuery.isFetching,
    connectionImpactLoading:
      previewDisconnect && connectionImpactQuery.isFetching,
    canManage,
    onSelectConnection: (connectionId) => {
      setSelectedConnectionId(connectionId);
      setRouteOffset(0);
      setDefaultOffset(0);
      setAgentId("");
      setProviderChannelId("");
      setDefaultRouteId("");
      setPreviewRouteId(null);
      setPreviewDisconnect(false);
      setActionError(null);
    },
    onSetupDraftChange: setSetupDraft,
    onEditDraftChange: setEditDraft,
    onDiscordSetupDraftChange: setDiscordSetupDraft,
    onDiscordEditDraftChange: setDiscordEditDraft,
    onAgentIdChange: setAgentId,
    onProviderChannelIdChange: setProviderChannelId,
    onDefaultRouteIdChange: setDefaultRouteId,
    onCreate: () => {
      setActionError(null);
      createMutation.mutate({
        handle,
        appId: setupDraft.appId,
        transport: setupDraft.transport,
        credentials: {
          botToken: setupDraft.credentials.botToken,
          signingSecret: setupDraft.credentials.signingSecret,
          appToken: setupDraft.credentials.appToken || null,
        },
      });
    },
    onCreateDiscord: () => {
      setActionError(null);
      createDiscordMutation.mutate({
        handle,
        appId: discordSetupDraft.appId,
        credentials: {
          botToken: discordSetupDraft.botToken,
          targetGuildId: discordSetupDraft.targetGuildId,
        },
      });
    },
    onSaveConnection: () => {
      if (selectedConnectionId === null) {
        return;
      }
      setActionError(null);
      updateMutation.mutate({
        handle,
        connectionId: selectedConnectionId,
        appId: editDraft.appId,
        transport: editDraft.transport,
        credentials: {
          botToken: editDraft.credentials.botToken,
          signingSecret: editDraft.credentials.signingSecret,
          appToken: editDraft.credentials.appToken || null,
        },
      });
    },
    onSaveDiscordConnection: () => {
      if (selectedConnectionId === null) {
        return;
      }
      setActionError(null);
      updateDiscordMutation.mutate({
        handle,
        connectionId: selectedConnectionId,
        appId: discordEditDraft.appId,
        credentials: {
          botToken: discordEditDraft.botToken,
          targetGuildId: discordEditDraft.targetGuildId,
        },
      });
    },
    onValidate: () => {
      if (selectedConnectionId !== null) {
        setActionError(null);
        validateMutation.mutate({ handle, connectionId: selectedConnectionId });
      }
    },
    onPreviewRouteRemoval: (routeId) => {
      setActionError(null);
      setPreviewRouteId(routeId);
    },
    onRemoveRoute: () => {
      if (
        selectedConnectionId !== null &&
        previewRouteId !== null &&
        generation !== null
      ) {
        setActionError(null);
        removeRouteMutation.mutate({
          handle,
          connectionId: selectedConnectionId,
          routeId: previewRouteId,
          expectedGeneration: routeImpactQuery.data?.generation ?? generation,
        });
      }
    },
    onReenableRoute: (routeId) => {
      if (selectedConnectionId !== null) {
        setActionError(null);
        reenableRouteMutation.mutate({
          handle,
          connectionId: selectedConnectionId,
          routeId,
        });
      }
    },
    onAddRoute: () => {
      if (selectedConnectionId !== null && agentId.trim() !== "") {
        setActionError(null);
        addRouteMutation.mutate({
          handle,
          connectionId: selectedConnectionId,
          agentId,
        });
      }
    },
    onSetDefault: () => {
      if (
        selectedConnectionId !== null &&
        providerChannelId.trim() !== "" &&
        defaultRouteId !== "" &&
        generation !== null
      ) {
        setActionError(null);
        replaceDefaultMutation.mutate({
          handle,
          connectionId: selectedConnectionId,
          providerChannelId,
          routeId: defaultRouteId,
          expectedGeneration: generation,
        });
      }
    },
    onClearDefault: (channelId) => {
      if (selectedConnectionId !== null && generation !== null) {
        setActionError(null);
        clearDefaultMutation.mutate({
          handle,
          connectionId: selectedConnectionId,
          providerChannelId: channelId,
          expectedGeneration: generation,
        });
      }
    },
    onPreviewDisconnect: () => {
      setActionError(null);
      setPreviewDisconnect(true);
    },
    onDisconnect: () => {
      if (selectedConnectionId !== null && generation !== null) {
        setActionError(null);
        disconnectMutation.mutate({
          handle,
          connectionId: selectedConnectionId,
          expectedGeneration:
            connectionImpactQuery.data?.generation ?? generation,
        });
      }
    },
    onCancelPreview: () => {
      setPreviewRouteId(null);
      setPreviewDisconnect(false);
    },
    onConnectionPage: (offset) => {
      setConnectionOffset(offset);
      setSelectedConnectionId(null);
      setRouteOffset(0);
      setDefaultOffset(0);
      setAgentId("");
      setProviderChannelId("");
      setDefaultRouteId("");
      setPreviewRouteId(null);
      setPreviewDisconnect(false);
      setActionError(null);
    },
    onRoutePage: (offset) => {
      setRouteOffset(offset);
      setDefaultRouteId("");
      setPreviewRouteId(null);
    },
    onDefaultPage: setDefaultOffset,
    onRetryRouteImpact: () => {
      void routeImpactQuery.refetch();
    },
    onRetryConnectionImpact: () => {
      void connectionImpactQuery.refetch();
    },
  };
}
