"use client";
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
import { useAgentAdminSectionController } from "../containers/useAgentAdminSectionController";
import type { AgentAdminSectionViewProps } from "../containers/useAgentAdminSectionController";
import type { MemberItem } from "../containers/useAgentFormContainer";
import type { AdminListState } from "../types";
/**
 * Agent admin management section.
 *
 * Handles Admin list display + add/remove on edit page.
 */
import type { AgentAdminResponse } from "@azents/public-client";

interface AgentAdminSectionProps {
  adminListState: AdminListState;
  members: MemberItem[];
  onAddAdmin: (workspaceUserId: string) => void;
  onRemoveAdmin: (admin: AgentAdminResponse) => void;
}

export function AgentAdminSection(
  props: AgentAdminSectionProps,
): React.ReactElement {
  return <AgentAdminSectionView {...useAgentAdminSectionController(props)} />;
}

export function AgentAdminSectionView({
  adminListState,
  onRemoveAdmin,
  t,
  selectedMemberId,
  setSelectedMemberId,
  availableMembers,
  getMemberName,
  handleAddAdmin,
}: AgentAdminSectionViewProps): React.ReactElement {
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
