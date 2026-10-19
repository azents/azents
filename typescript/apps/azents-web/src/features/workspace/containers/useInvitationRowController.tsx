"use client";
import { useModals } from "@mantine/modals";
import { useTranslations } from "next-intl";
import { useLocale } from "@/shared/providers/locale";
import type { WorkspaceInvitation } from "../types";
function useRoleLabel(role: string): string {
  const t = useTranslations("workspace.dashboard");
  if (role === "owner") {
    return t("roleOwner");
  }
  if (role === "manager") {
    return t("roleManager");
  }
  return t("roleMember");
}
export interface InvitationRowViewProps {
  invitation: WorkspaceInvitation;
  canManage: boolean;
  t: ReturnType<typeof useTranslations<"workspace.dashboard">>;
  locale: "en-US" | "ko-KR" | "ja-JP" | "fr-FR";
  roleLabel: string;
  confirmInvitationAction1: () => void;
}
export function useInvitationRowController({
  invitation,
  canManage,
  onCancel,
}: {
  invitation: WorkspaceInvitation;
  canManage: boolean;
  onCancel: () => void;
}): InvitationRowViewProps {
  const t = useTranslations("workspace.dashboard");
  const modals = useModals();
  const { locale } = useLocale();
  const roleLabel = useRoleLabel(invitation.role);

  function confirmInvitationAction1(): void {
    modals.openConfirmModal({
      title: t("cancelInvitation"),
      children: t("cancelInvitationConfirm"),
      labels: {
        confirm: t("cancelInvitation"),
        cancel: t("cancel"),
      },
      confirmProps: { color: "red" },
      onConfirm: () => onCancel(),
    });
  }
  return {
    invitation,
    canManage,
    t,
    locale,
    roleLabel,
    confirmInvitationAction1,
  };
}
