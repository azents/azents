"use client";
import { Text } from "@mantine/core";
import { useModals } from "@mantine/modals";
import { useTranslations } from "next-intl";
import type { SessionChannelsContainerOutput } from "./useSessionChannelsContainer";
import type { ManagedBinding } from "@azents/public-client";
type SessionChannelsProps = Omit<
  SessionChannelsContainerOutput,
  "session" | "onUpdateTitle"
>;

export interface SessionChannelsViewProps {
  agent: SessionChannelsProps["agent"];
  state: SessionChannelsProps["state"];
  actionError: SessionChannelsProps["actionError"];
  disconnectingId: SessionChannelsProps["disconnectingId"];
  responseModeDrafts: SessionChannelsProps["responseModeDrafts"];
  updatingResponseModeId: SessionChannelsProps["updatingResponseModeId"];
  responseModeError: SessionChannelsProps["responseModeError"];
  onDisconnect: SessionChannelsProps["onDisconnect"];
  onResponseModeChange: SessionChannelsProps["onResponseModeChange"];
  onSaveResponseMode: SessionChannelsProps["onSaveResponseMode"];
  t: ReturnType<typeof useTranslations<"workspace.agents.sessionChannels">>;
  openDisconnectConfirm: (binding: ManagedBinding) => void;
}
export function useSessionChannelsController({
  agent,
  state,
  actionError,
  disconnectingId,
  responseModeDrafts,
  updatingResponseModeId,
  responseModeError,
  onDisconnect,
  onResponseModeChange,
  onSaveResponseMode,
}: SessionChannelsProps): SessionChannelsViewProps {
  const t = useTranslations("workspace.agents.sessionChannels");
  const modals = useModals();
  const openDisconnectConfirm = (binding: ManagedBinding): void => {
    modals.openConfirmModal({
      title: t("disconnect"),
      children: <Text size="sm">{t("disconnectConfirm")}</Text>,
      labels: { confirm: t("disconnect"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () => onDisconnect(binding),
    });
  };
  return {
    agent,
    state,
    actionError,
    disconnectingId,
    responseModeDrafts,
    updatingResponseModeId,
    responseModeError,
    onDisconnect,
    onResponseModeChange,
    onSaveResponseMode,
    t,
    openDisconnectConfirm,
  };
}
