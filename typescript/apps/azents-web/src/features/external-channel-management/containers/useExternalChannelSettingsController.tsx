"use client";
import { Text } from "@mantine/core";
import { useModals } from "@mantine/modals";
import { useTranslations } from "next-intl";
import type { ExternalChannelSettingsContainerOutput } from "./useExternalChannelSettingsContainer";

export interface ExternalChannelSettingsViewProps {
  handle: ExternalChannelSettingsContainerOutput["handle"];
  state: ExternalChannelSettingsContainerOutput["state"];
  manifestState: ExternalChannelSettingsContainerOutput["manifestState"];
  dialogState: ExternalChannelSettingsContainerOutput["dialogState"];
  discordDialogState: ExternalChannelSettingsContainerOutput["discordDialogState"];
  actionError: ExternalChannelSettingsContainerOutput["actionError"];
  actionTarget: ExternalChannelSettingsContainerOutput["actionTarget"];
  actionsBusy: ExternalChannelSettingsContainerOutput["actionsBusy"];
  discordThreadDurationDrafts: ExternalChannelSettingsContainerOutput["discordThreadDurationDrafts"];
  discordThreadDurationSavedConnectionId: ExternalChannelSettingsContainerOutput["discordThreadDurationSavedConnectionId"];
  discordUrlPreviewDrafts: ExternalChannelSettingsContainerOutput["discordUrlPreviewDrafts"];
  discordUrlPreviewSavedConnectionId: ExternalChannelSettingsContainerOutput["discordUrlPreviewSavedConnectionId"];
  defaultResponseMode: ExternalChannelSettingsContainerOutput["defaultResponseMode"];
  defaultResponseModeDraft: ExternalChannelSettingsContainerOutput["defaultResponseModeDraft"];
  defaultResponseModeSaving: ExternalChannelSettingsContainerOutput["defaultResponseModeSaving"];
  defaultResponseModeError: ExternalChannelSettingsContainerOutput["defaultResponseModeError"];
  defaultResponseModeSaved: ExternalChannelSettingsContainerOutput["defaultResponseModeSaved"];
  canManageWorkspaceMultiApps: ExternalChannelSettingsContainerOutput["canManageWorkspaceMultiApps"];
  onDefaultResponseModeChange: ExternalChannelSettingsContainerOutput["onDefaultResponseModeChange"];
  onSaveDefaultResponseMode: ExternalChannelSettingsContainerOutput["onSaveDefaultResponseMode"];
  onOpenSetup: ExternalChannelSettingsContainerOutput["onOpenSetup"];
  onOpenDiscordSetup: ExternalChannelSettingsContainerOutput["onOpenDiscordSetup"];
  onOpenEdit: ExternalChannelSettingsContainerOutput["onOpenEdit"];
  onCloseDialog: ExternalChannelSettingsContainerOutput["onCloseDialog"];
  onDialogChange: ExternalChannelSettingsContainerOutput["onDialogChange"];
  onSubmitDialog: ExternalChannelSettingsContainerOutput["onSubmitDialog"];
  onCloseDiscordDialog: ExternalChannelSettingsContainerOutput["onCloseDiscordDialog"];
  onDiscordDialogChange: ExternalChannelSettingsContainerOutput["onDiscordDialogChange"];
  onSubmitDiscordDialog: ExternalChannelSettingsContainerOutput["onSubmitDiscordDialog"];
  onValidate: ExternalChannelSettingsContainerOutput["onValidate"];
  onDisconnect: ExternalChannelSettingsContainerOutput["onDisconnect"];
  onUpdateAccessPolicy: ExternalChannelSettingsContainerOutput["onUpdateAccessPolicy"];
  onDiscordThreadDurationChange: ExternalChannelSettingsContainerOutput["onDiscordThreadDurationChange"];
  onSaveDiscordThreadDuration: ExternalChannelSettingsContainerOutput["onSaveDiscordThreadDuration"];
  onDiscordUrlPreviewChange: ExternalChannelSettingsContainerOutput["onDiscordUrlPreviewChange"];
  onSaveDiscordUrlPreview: ExternalChannelSettingsContainerOutput["onSaveDiscordUrlPreview"];
  onRevokeGrant: ExternalChannelSettingsContainerOutput["onRevokeGrant"];
  onRemoveBlock: ExternalChannelSettingsContainerOutput["onRemoveBlock"];
  t: ReturnType<typeof useTranslations<"workspace.agents.externalChannels">>;
  loaded: Extract<
    ExternalChannelSettingsContainerOutput["state"],
    { type: "LOADED" }
  > | null;
  openConfirm: ({
    title,
    description,
    confirmLabel,
    onConfirm,
  }: {
    title: string;
    description: string;
    confirmLabel: string;
    onConfirm: () => void;
  }) => void;
}
export function useExternalChannelSettingsController({
  handle,
  state,
  manifestState,
  dialogState,
  discordDialogState,
  actionError,
  actionTarget,
  actionsBusy,
  discordThreadDurationDrafts,
  discordThreadDurationSavedConnectionId,
  discordUrlPreviewDrafts,
  discordUrlPreviewSavedConnectionId,
  defaultResponseMode,
  defaultResponseModeDraft,
  defaultResponseModeSaving,
  defaultResponseModeError,
  defaultResponseModeSaved,
  canManageWorkspaceMultiApps,
  onDefaultResponseModeChange,
  onSaveDefaultResponseMode,
  onOpenSetup,
  onOpenDiscordSetup,
  onOpenEdit,
  onCloseDialog,
  onDialogChange,
  onSubmitDialog,
  onCloseDiscordDialog,
  onDiscordDialogChange,
  onSubmitDiscordDialog,
  onValidate,
  onDisconnect,
  onUpdateAccessPolicy,
  onDiscordThreadDurationChange,
  onSaveDiscordThreadDuration,
  onDiscordUrlPreviewChange,
  onSaveDiscordUrlPreview,
  onRevokeGrant,
  onRemoveBlock,
}: ExternalChannelSettingsContainerOutput): ExternalChannelSettingsViewProps {
  const t = useTranslations("workspace.agents.externalChannels");
  const modals = useModals();
  const loaded = state.type === "LOADED" ? state : null;
  const openConfirm = ({
    title,
    description,
    confirmLabel,
    onConfirm,
  }: {
    title: string;
    description: string;
    confirmLabel: string;
    onConfirm: () => void;
  }): void => {
    modals.openConfirmModal({
      title,
      children: <Text size="sm">{description}</Text>,
      labels: { confirm: confirmLabel, cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm,
    });
  };
  return {
    handle,
    state,
    manifestState,
    dialogState,
    discordDialogState,
    actionError,
    actionTarget,
    actionsBusy,
    discordThreadDurationDrafts,
    discordThreadDurationSavedConnectionId,
    discordUrlPreviewDrafts,
    discordUrlPreviewSavedConnectionId,
    defaultResponseMode,
    defaultResponseModeDraft,
    defaultResponseModeSaving,
    defaultResponseModeError,
    defaultResponseModeSaved,
    canManageWorkspaceMultiApps,
    onDefaultResponseModeChange,
    onSaveDefaultResponseMode,
    onOpenSetup,
    onOpenDiscordSetup,
    onOpenEdit,
    onCloseDialog,
    onDialogChange,
    onSubmitDialog,
    onCloseDiscordDialog,
    onDiscordDialogChange,
    onSubmitDiscordDialog,
    onValidate,
    onDisconnect,
    onUpdateAccessPolicy,
    onDiscordThreadDurationChange,
    onSaveDiscordThreadDuration,
    onDiscordUrlPreviewChange,
    onSaveDiscordUrlPreview,
    onRevokeGrant,
    onRemoveBlock,
    t,
    loaded,
    openConfirm,
  };
}
