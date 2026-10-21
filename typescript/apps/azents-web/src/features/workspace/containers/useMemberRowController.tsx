"use client";
import { useModals } from "@mantine/modals";
import { useTranslations } from "next-intl";
import { useLocale } from "@/shared/providers/locale";
import type { WorkspaceMember } from "../types";
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
export interface MemberRowViewProps {
  member: WorkspaceMember;
  isCurrentUser: boolean;
  canManage: boolean;
  onUpdateRole: (
    workspaceUserId: string,
    role: "owner" | "manager" | "member",
  ) => void;
  t: ReturnType<typeof useTranslations<"workspace.dashboard">>;
  locale: "en-US" | "ko-KR" | "ja-JP" | "fr-FR";
  roleLabel: string;
  showControls: boolean;
  confirmMemberAction1: () => void;
}
export function useMemberRowController({
  member,
  isCurrentUser,
  canManage,
  onUpdateRole,
  onRemoveMember,
}: {
  member: WorkspaceMember;
  isCurrentUser: boolean;
  canManage: boolean;
  onUpdateRole: (
    workspaceUserId: string,
    role: "owner" | "manager" | "member",
  ) => void;
  onRemoveMember: (workspaceUserId: string) => void;
}): MemberRowViewProps {
  const t = useTranslations("workspace.dashboard");
  const modals = useModals();
  const { locale } = useLocale();
  const roleLabel = useRoleLabel(member.role);
  const isOwner = member.role === "owner";
  // Management control condition: manager+ permission && not self && target is not owner
  const showControls = canManage && !isCurrentUser && !isOwner;

  function confirmMemberAction1(): void {
    modals.openConfirmModal({
      title: t("removeMember"),
      children: t("removeMemberConfirm"),
      labels: { confirm: t("removeMember"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      onConfirm: () => onRemoveMember(member.id),
    });
  }
  return {
    member,
    isCurrentUser,
    canManage,
    onUpdateRole,
    t,
    locale,
    roleLabel,
    showControls,
    confirmMemberAction1,
  };
}
