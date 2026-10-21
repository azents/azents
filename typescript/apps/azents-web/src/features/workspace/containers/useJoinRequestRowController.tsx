"use client";
import { useModals } from "@mantine/modals";
import { useTranslations } from "next-intl";
import { useLocale } from "@/shared/providers/locale";
import type { WorkspaceJoinRequest } from "../types";

export interface JoinRequestRowViewProps {
  joinRequest: {
    joinRequest: WorkspaceJoinRequest;
    onApprove: () => void;
    onReject: () => void;
    onMute: () => void;
    onDelete: () => void;
  }["joinRequest"];
  onMute: {
    joinRequest: WorkspaceJoinRequest;
    onApprove: () => void;
    onReject: () => void;
    onMute: () => void;
    onDelete: () => void;
  }["onMute"];
  t: ReturnType<typeof useTranslations<"workspace.dashboard">>;
  locale: "en-US" | "ko-KR" | "ja-JP" | "fr-FR";
  confirmJoinRequestAction1: () => void;
  confirmJoinRequestAction2: () => void;
  confirmJoinRequestAction3: () => void;
}
export function useJoinRequestRowController({
  joinRequest,
  onApprove,
  onReject,
  onMute,
  onDelete,
}: {
  joinRequest: WorkspaceJoinRequest;
  onApprove: () => void;
  onReject: () => void;
  onMute: () => void;
  onDelete: () => void;
}): JoinRequestRowViewProps {
  const t = useTranslations("workspace.dashboard");
  const modals = useModals();
  const { locale } = useLocale();

  function confirmJoinRequestAction1(): void {
    modals.openConfirmModal({
      title: t("approveRequest"),
      children: t("approveConfirm"),
      labels: {
        confirm: t("approveRequest"),
        cancel: t("cancel"),
      },
      confirmProps: { color: "green" },
      onConfirm: () => onApprove(),
    });
  }

  function confirmJoinRequestAction2(): void {
    modals.openConfirmModal({
      title: t("rejectRequest"),
      children: t("rejectConfirm"),
      labels: {
        confirm: t("rejectRequest"),
        cancel: t("cancel"),
      },
      confirmProps: { color: "red" },
      onConfirm: () => onReject(),
    });
  }

  function confirmJoinRequestAction3(): void {
    modals.openConfirmModal({
      title: t("deleteRequest"),
      children: t("deleteJoinRequestConfirm"),
      labels: {
        confirm: t("deleteRequest"),
        cancel: t("cancel"),
      },
      confirmProps: { color: "red" },
      onConfirm: () => onDelete(),
    });
  }
  return {
    joinRequest,
    onMute,
    t,
    locale,
    confirmJoinRequestAction1,
    confirmJoinRequestAction2,
    confirmJoinRequestAction3,
  };
}
