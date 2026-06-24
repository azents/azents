"use client";

/**
 * Agent admin management section.
 *
 * Handles Admin list display + add/remove on edit page.
 */

import {
  Alert,
  Button,
  Divider,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import type { MemberItem } from "../containers/useAgentFormContainer";
import type { AdminListState } from "../types";
import type { AgentAdminResponse } from "@azents/public-client";

interface AgentAdminSectionProps {
  adminListState: AdminListState;
  members: MemberItem[];
  onAddAdmin: (workspaceUserId: string) => void;
  onRemoveAdmin: (admin: AgentAdminResponse) => void;
}

export function AgentAdminSection({
  adminListState,
  members,
  onAddAdmin,
  onRemoveAdmin,
}: AgentAdminSectionProps): React.ReactElement {
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

  return (
    <>
      <Divider />
      <Title order={5}>{t("adminsSection")}</Title>

      {adminListState.type === "LOADING" && <Loader size="sm" />}
      {adminListState.type === "ERROR" && (
        <Alert color="red">{t("loadError")}</Alert>
      )}
      {adminListState.type === "READY" && (
        <Stack gap="xs">
          {adminListState.admins.map((admin) => (
            <Group key={admin.id} justify="space-between">
              <Text size="sm">{getMemberName(admin.workspace_user_id)}</Text>
              <Button
                variant="subtle"
                color="red"
                size="xs"
                onClick={() => onRemoveAdmin(admin)}
                disabled={adminListState.admins.length <= 1}
              >
                {t("removeAdmin")}
              </Button>
            </Group>
          ))}

          {adminListState.admins.length <= 1 && (
            <Text size="xs" c="dimmed">
              {t("lastAdminWarning")}
            </Text>
          )}

          {/* Add Admin */}
          <Group gap="sm" mt="xs">
            <Select
              placeholder={t("adminAddPlaceholder")}
              data={availableMembers}
              value={selectedMemberId}
              onChange={setSelectedMemberId}
              style={{ flex: 1 }}
              clearable
            />
            <Button
              size="sm"
              variant="light"
              onClick={handleAddAdmin}
              disabled={!selectedMemberId}
            >
              {t("addAdmin")}
            </Button>
          </Group>
        </Stack>
      )}
    </>
  );
}
