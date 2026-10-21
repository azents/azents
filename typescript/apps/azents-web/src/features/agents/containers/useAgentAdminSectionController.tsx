"use client";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import type { AdminListState } from "../types";
import type { MemberItem } from "./useAgentFormContainer";
import type { AgentAdminResponse } from "@azents/public-client";
interface AgentAdminSectionProps {
  readOnly: boolean;
  adminListState: AdminListState;
  members: MemberItem[];
  onAddAdmin: (workspaceUserId: string) => void;
  onRemoveAdmin: (admin: AgentAdminResponse) => void;
}

export interface AgentAdminSectionViewProps {
  readOnly: boolean;
  adminListState: AgentAdminSectionProps["adminListState"];
  onRemoveAdmin: AgentAdminSectionProps["onRemoveAdmin"];
  t: ReturnType<typeof useTranslations<"workspace.agents">>;
  selectedMemberId: string | null;
  setSelectedMemberId: React.Dispatch<React.SetStateAction<string | null>>;
  availableMembers: { value: string; label: string }[];
  getMemberName: (workspaceUserId: string) => string;
  handleAddAdmin: () => void;
}
export function useAgentAdminSectionController({
  readOnly,
  adminListState,
  members,
  onAddAdmin,
  onRemoveAdmin,
}: AgentAdminSectionProps): AgentAdminSectionViewProps {
  const t = useTranslations("workspace.agents");
  const [selectedMemberId, setSelectedMemberId] = useState<string | null>(null);

  // Only non-Admin members can be added
  const availableMembers = useMemo(() => {
    if (adminListState.type !== "READY") {
      return [];
    }
    const adminUserIds = new Set(
      adminListState.admins.map((a) => a.workspace_user_id),
    );
    return members
      .filter((m) => !adminUserIds.has(m.id))
      .map((m) => ({ value: m.id, label: `${m.name} (${m.role})` }));
  }, [adminListState, members]);

  // Member name lookup helper
  const getMemberName = (workspaceUserId: string): string => {
    const member = members.find((m) => m.id === workspaceUserId);
    return member?.name ?? workspaceUserId;
  };

  const handleAddAdmin = (): void => {
    if (selectedMemberId) {
      onAddAdmin(selectedMemberId);
      setSelectedMemberId(null);
    }
  };
  return {
    readOnly,
    adminListState,
    onRemoveAdmin,
    t,
    selectedMemberId,
    setSelectedMemberId,
    availableMembers,
    getMemberName,
    handleAddAdmin,
  };
}
