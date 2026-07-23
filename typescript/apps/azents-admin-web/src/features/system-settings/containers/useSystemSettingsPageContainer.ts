"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  ExternalChannelFilesDraft,
  ExternalChannelFilesPageState,
  PlatformGitHubAppDraft,
  PlatformGitHubAppPageState,
  SystemSettingAuditState,
} from "../types";
import type { PlatformGitHubAppDetailResponse } from "@azents/admin-client";

interface SecretActionReplace {
  action: "replace";
  value: string;
}

interface SecretActionClear {
  action: "clear";
}

type SecretAction = SecretActionReplace | SecretActionClear;

export interface SystemSettingsPageContentProps {
  externalFilesState: ExternalChannelFilesPageState;
  externalFilesDraft: ExternalChannelFilesDraft;
  externalFilesSaving: boolean;
  externalFilesDraftDirty: boolean;
  externalFilesSaveDisabled: boolean;
  externalFilesMutationError: string | null;
  state: PlatformGitHubAppPageState;
  auditState: SystemSettingAuditState;
  draft: PlatformGitHubAppDraft;
  confirmationAction: string | null;
  confirmationActions: string[];
  saving: boolean;
  validating: boolean;
  confirming: boolean;
  cancelling: boolean;
  checkingHealth: boolean;
  saveDisabled: boolean;
  mutationError: string | null;
  onInboundMaxFileMiBChange: (value: number | string) => void;
  onOutboundMaxFileMiBChange: (value: number | string) => void;
  onOutboundMaxActionMiBChange: (value: number | string) => void;
  onSaveExternalFiles: () => void;
  onAppIdChange: (value: string) => void;
  onClientIdChange: (value: string) => void;
  onPrivateKeyChange: (value: string) => void;
  onClientSecretChange: (value: string) => void;
  onClearPrivateKeyChange: (checked: boolean) => void;
  onClearClientSecretChange: (checked: boolean) => void;
  onConfirmationActionChange: (value: string) => void;
  onSaveCandidate: () => void;
  onValidateCandidate: () => void;
  onConfirmCandidate: () => void;
  onCancelCandidate: () => void;
  onCheckHealth: () => void;
}

const BYTES_PER_MIB = 1024 * 1024;
const MAX_FILE_MIB = 100;
const MAX_ACTION_MIB = 2_000;

const EMPTY_EXTERNAL_FILES_DRAFT: ExternalChannelFilesDraft = {
  inboundMaxFileMiB: "",
  outboundMaxFileMiB: "",
  outboundMaxActionMiB: "",
};

const EMPTY_DRAFT: PlatformGitHubAppDraft = {
  appId: "",
  clientId: "",
  privateKey: "",
  clientSecret: "",
  appIdTouched: false,
  clientIdTouched: false,
  clearPrivateKey: false,
  clearClientSecret: false,
};

function bytesToMiB(value: number): number {
  return value / BYTES_PER_MIB;
}

function draftMiBToBytes(
  value: number | string,
  maximumMiB: number,
): number | null {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    !Number.isInteger(value) ||
    value <= 0 ||
    value > maximumMiB
  ) {
    return null;
  }
  return value * BYTES_PER_MIB;
}

function fieldValue(
  detail: PlatformGitHubAppDetailResponse,
  name: string,
): string {
  return detail.fields.find((field) => field.name === name)?.value ?? "";
}

function confirmationActions(
  detail?: PlatformGitHubAppDetailResponse,
): string[] {
  const raw = detail?.candidate?.impact?.confirmation_actions;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.filter((item): item is string => typeof item === "string");
}

function secretAction(clear: boolean, value: string): SecretAction | null {
  if (clear) {
    return { action: "clear" };
  }
  if (value.length > 0) {
    return { action: "replace", value };
  }
  return null;
}

export function useSystemSettingsPageContainer(): SystemSettingsPageContentProps {
  const utils = trpc.useUtils();
  const externalFilesQuery =
    trpc.systemSettings.getExternalChannelFiles.useQuery();
  const detailQuery = trpc.systemSettings.getPlatformGitHubApp.useQuery();
  const auditQuery = trpc.systemSettings.listAuditEvents.useQuery({
    offset: 0,
    limit: 20,
  });
  const [externalFilesDraft, setExternalFilesDraft] =
    useState<ExternalChannelFilesDraft>(EMPTY_EXTERNAL_FILES_DRAFT);
  const [draft, setDraft] = useState<PlatformGitHubAppDraft>(EMPTY_DRAFT);
  const [confirmationAction, setConfirmationAction] = useState<string | null>(
    null,
  );
  const initializedExternalFilesVersion = useRef<number | null>(null);
  const initializedVersion = useRef<number | null>(null);

  useEffect(() => {
    const detail = externalFilesQuery.data;
    if (
      !detail ||
      initializedExternalFilesVersion.current === detail.admin_version
    ) {
      return;
    }
    initializedExternalFilesVersion.current = detail.admin_version;
    setExternalFilesDraft({
      inboundMaxFileMiB: bytesToMiB(detail.inbound_max_file_bytes),
      outboundMaxFileMiB: bytesToMiB(detail.outbound_max_file_bytes),
      outboundMaxActionMiB: bytesToMiB(detail.outbound_max_action_bytes),
    });
  }, [externalFilesQuery.data]);

  useEffect(() => {
    const detail = detailQuery.data;
    if (!detail || initializedVersion.current === detail.admin_version) {
      return;
    }
    initializedVersion.current = detail.admin_version;
    setDraft({
      ...EMPTY_DRAFT,
      appId: fieldValue(detail, "app_id"),
      clientId: fieldValue(detail, "client_id"),
    });
  }, [detailQuery.data]);

  const actions = useMemo(
    () => confirmationActions(detailQuery.data),
    [detailQuery.data],
  );

  useEffect(() => {
    const candidateId = detailQuery.data?.candidate?.id;
    if (!candidateId) {
      setConfirmationAction(null);
      return;
    }
    setConfirmationAction((current) =>
      current && actions.includes(current) ? current : (actions[0] ?? null),
    );
  }, [actions, detailQuery.data?.candidate?.id]);

  const invalidate = useCallback(async (): Promise<void> => {
    await Promise.all([
      utils.systemSettings.getPlatformGitHubApp.invalidate(),
      utils.systemSettings.listAuditEvents.invalidate(),
    ]);
  }, [utils.systemSettings]);

  const invalidateExternalFiles = useCallback(async (): Promise<void> => {
    await Promise.all([
      utils.systemSettings.getExternalChannelFiles.invalidate(),
      utils.systemSettings.listAuditEvents.invalidate(),
    ]);
  }, [utils.systemSettings]);

  const externalFilesPatchMutation =
    trpc.systemSettings.patchExternalChannelFiles.useMutation({
      onSuccess: invalidateExternalFiles,
    });
  const patchMutation = trpc.systemSettings.patchPlatformGitHubApp.useMutation({
    onSuccess: async () => {
      setDraft((current) => ({
        ...current,
        privateKey: "",
        clientSecret: "",
        appIdTouched: false,
        clientIdTouched: false,
        clearPrivateKey: false,
        clearClientSecret: false,
      }));
      await invalidate();
    },
  });
  const validateMutation =
    trpc.systemSettings.validatePlatformGitHubAppCandidate.useMutation({
      onSuccess: invalidate,
    });
  const confirmMutation =
    trpc.systemSettings.confirmPlatformGitHubAppCandidate.useMutation({
      onSuccess: invalidate,
    });
  const cancelMutation =
    trpc.systemSettings.cancelPlatformGitHubAppCandidate.useMutation({
      onSuccess: invalidate,
    });
  const healthMutation =
    trpc.systemSettings.checkPlatformGitHubAppHealth.useMutation({
      onSuccess: invalidate,
    });

  const externalFilesState = useMemo<ExternalChannelFilesPageState>(() => {
    if (externalFilesQuery.isPending) {
      return { type: "LOADING" };
    }
    if (externalFilesQuery.isError) {
      return { type: "ERROR", message: externalFilesQuery.error.message };
    }
    return { type: "LOADED", detail: externalFilesQuery.data };
  }, [
    externalFilesQuery.data,
    externalFilesQuery.error?.message,
    externalFilesQuery.isError,
    externalFilesQuery.isPending,
  ]);

  const state = useMemo<PlatformGitHubAppPageState>(() => {
    if (detailQuery.isPending) {
      return { type: "LOADING" };
    }
    if (detailQuery.isError) {
      return { type: "ERROR", message: detailQuery.error.message };
    }
    return { type: "LOADED", detail: detailQuery.data };
  }, [
    detailQuery.data,
    detailQuery.error?.message,
    detailQuery.isError,
    detailQuery.isPending,
  ]);

  const auditState = useMemo<SystemSettingAuditState>(() => {
    if (auditQuery.isPending) {
      return { type: "LOADING" };
    }
    if (auditQuery.isError) {
      return { type: "ERROR", message: auditQuery.error.message };
    }
    return {
      type: "LOADED",
      events: auditQuery.data.items,
      total: auditQuery.data.total,
    };
  }, [
    auditQuery.data,
    auditQuery.error?.message,
    auditQuery.isError,
    auditQuery.isPending,
  ]);

  const privateKeyAction = secretAction(
    draft.clearPrivateKey,
    draft.privateKey,
  );
  const clientSecretAction = secretAction(
    draft.clearClientSecret,
    draft.clientSecret,
  );
  const inboundMaxFileBytes = draftMiBToBytes(
    externalFilesDraft.inboundMaxFileMiB,
    MAX_FILE_MIB,
  );
  const outboundMaxFileBytes = draftMiBToBytes(
    externalFilesDraft.outboundMaxFileMiB,
    MAX_FILE_MIB,
  );
  const outboundMaxActionBytes = draftMiBToBytes(
    externalFilesDraft.outboundMaxActionMiB,
    MAX_ACTION_MIB,
  );
  const externalFilesDraftValid =
    inboundMaxFileBytes !== null &&
    outboundMaxFileBytes !== null &&
    outboundMaxActionBytes !== null &&
    outboundMaxActionBytes >= outboundMaxFileBytes;
  const externalFilesDraftDirty =
    externalFilesState.type === "LOADED" &&
    (externalFilesDraft.inboundMaxFileMiB !==
      bytesToMiB(externalFilesState.detail.inbound_max_file_bytes) ||
      externalFilesDraft.outboundMaxFileMiB !==
        bytesToMiB(externalFilesState.detail.outbound_max_file_bytes) ||
      externalFilesDraft.outboundMaxActionMiB !==
        bytesToMiB(externalFilesState.detail.outbound_max_action_bytes));
  const externalFilesSaveDisabled =
    externalFilesState.type !== "LOADED" ||
    !externalFilesDraftValid ||
    !externalFilesDraftDirty ||
    externalFilesPatchMutation.isPending;
  const saveDisabled =
    state.type !== "LOADED" ||
    (!draft.appIdTouched &&
      !draft.clientIdTouched &&
      privateKeyAction === null &&
      clientSecretAction === null) ||
    patchMutation.isPending;

  const onSaveExternalFiles = useCallback((): void => {
    if (
      externalFilesState.type !== "LOADED" ||
      inboundMaxFileBytes === null ||
      outboundMaxFileBytes === null ||
      outboundMaxActionBytes === null ||
      outboundMaxActionBytes < outboundMaxFileBytes
    ) {
      return;
    }
    externalFilesPatchMutation.mutate({
      expectedVersion: externalFilesState.detail.admin_version,
      inboundMaxFileBytes,
      outboundMaxFileBytes,
      outboundMaxActionBytes,
    });
  }, [
    externalFilesPatchMutation,
    externalFilesState,
    inboundMaxFileBytes,
    outboundMaxActionBytes,
    outboundMaxFileBytes,
  ]);

  const onSaveCandidate = useCallback((): void => {
    if (state.type !== "LOADED" || saveDisabled) {
      return;
    }
    patchMutation.mutate({
      expectedVersion: state.detail.admin_version,
      ...(draft.appIdTouched && {
        appId: draft.appId.trim() || null,
      }),
      ...(draft.clientIdTouched && {
        clientId: draft.clientId.trim() || null,
      }),
      ...(privateKeyAction !== null && {
        privateKey: privateKeyAction,
      }),
      ...(clientSecretAction !== null && {
        clientSecret: clientSecretAction,
      }),
    });
  }, [
    clientSecretAction,
    draft,
    patchMutation,
    privateKeyAction,
    saveDisabled,
    state,
  ]);

  const onValidateCandidate = useCallback((): void => {
    validateMutation.mutate();
  }, [validateMutation]);

  const onConfirmCandidate = useCallback((): void => {
    if (
      state.type !== "LOADED" ||
      !state.detail.candidate ||
      confirmationAction === null
    ) {
      return;
    }
    confirmMutation.mutate({
      candidateId: state.detail.candidate.id,
      expectedVersion: state.detail.admin_version,
      confirmationAction,
    });
  }, [confirmationAction, confirmMutation, state]);

  const onCancelCandidate = useCallback((): void => {
    if (state.type !== "LOADED" || !state.detail.candidate) {
      return;
    }
    cancelMutation.mutate({ candidateId: state.detail.candidate.id });
  }, [cancelMutation, state]);

  const onCheckHealth = useCallback((): void => {
    healthMutation.mutate();
  }, [healthMutation]);

  const mutationError =
    patchMutation.error?.message ??
    validateMutation.error?.message ??
    confirmMutation.error?.message ??
    cancelMutation.error?.message ??
    healthMutation.error?.message ??
    null;

  return {
    externalFilesState,
    externalFilesDraft,
    externalFilesSaving: externalFilesPatchMutation.isPending,
    externalFilesDraftDirty,
    externalFilesSaveDisabled,
    externalFilesMutationError:
      externalFilesPatchMutation.error?.message ?? null,
    state,
    auditState,
    draft,
    confirmationAction,
    confirmationActions: actions,
    saving: patchMutation.isPending,
    validating: validateMutation.isPending,
    confirming: confirmMutation.isPending,
    cancelling: cancelMutation.isPending,
    checkingHealth: healthMutation.isPending,
    saveDisabled,
    mutationError,
    onInboundMaxFileMiBChange: (value) =>
      setExternalFilesDraft((current) => ({
        ...current,
        inboundMaxFileMiB: value,
      })),
    onOutboundMaxFileMiBChange: (value) =>
      setExternalFilesDraft((current) => ({
        ...current,
        outboundMaxFileMiB: value,
      })),
    onOutboundMaxActionMiBChange: (value) =>
      setExternalFilesDraft((current) => ({
        ...current,
        outboundMaxActionMiB: value,
      })),
    onSaveExternalFiles,
    onAppIdChange: (value) =>
      setDraft((current) => ({
        ...current,
        appId: value,
        appIdTouched: true,
      })),
    onClientIdChange: (value) =>
      setDraft((current) => ({
        ...current,
        clientId: value,
        clientIdTouched: true,
      })),
    onPrivateKeyChange: (value) =>
      setDraft((current) => ({
        ...current,
        privateKey: value,
        clearPrivateKey: false,
      })),
    onClientSecretChange: (value) =>
      setDraft((current) => ({
        ...current,
        clientSecret: value,
        clearClientSecret: false,
      })),
    onClearPrivateKeyChange: (checked) =>
      setDraft((current) => ({
        ...current,
        privateKey: checked ? "" : current.privateKey,
        clearPrivateKey: checked,
      })),
    onClearClientSecretChange: (checked) =>
      setDraft((current) => ({
        ...current,
        clientSecret: checked ? "" : current.clientSecret,
        clearClientSecret: checked,
      })),
    onConfirmationActionChange: setConfirmationAction,
    onSaveCandidate,
    onValidateCandidate,
    onConfirmCandidate,
    onCancelCandidate,
    onCheckHealth,
  };
}
