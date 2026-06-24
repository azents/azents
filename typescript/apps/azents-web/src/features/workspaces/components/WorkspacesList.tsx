"use client";

/**
 * Workspace list UI component
 *
 * Displays workspaces user belongs to as cards.
 * Also displays invited workspaces in separate section.
 * On selection, moves to workspace dashboard; bottom has create new workspace button.
 */
import {
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconCheck, IconPlus, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { WorkspacesListContainerProps } from "../containers/useWorkspacesList";
import type {
  InvitationsState,
  ReceivedInvitation,
  WorkspacesListState,
} from "../types";

/** Convert role display name */
function useRoleLabel(role: string): string {
  const t = useTranslations("workspaces.invitations");
  if (role === "manager") {
    return t("roleManager");
  }
  return t("roleMember");
}

/** Invitation card component */
function InvitationCard({
  invitation,
  onAccept,
  onDecline,
  isAccepting,
  isDeclining,
}: {
  invitation: ReceivedInvitation;
  onAccept: () => void;
  onDecline: () => void;
  isAccepting: boolean;
  isDeclining: boolean;
}): React.ReactElement {
  const t = useTranslations("workspaces.invitations");
  const roleLabel = useRoleLabel(invitation.role);

  return (
    <Box
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: 12,
        padding: "12px 16px",
      }}
    >
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Box>
            <Text fw={600} size="sm">
              {invitation.workspace_name}
            </Text>
            <Text c="dimmed" size="xs">
              @{invitation.workspace_handle}
            </Text>
          </Box>
          <Badge variant="light" size="sm">
            {t("invitedAs", { role: roleLabel })}
          </Badge>
        </Group>
        <Group gap="xs">
          <Button
            size="xs"
            variant="filled"
            leftSection={<IconCheck size={14} />}
            onClick={onAccept}
            loading={isAccepting}
            disabled={isDeclining}
          >
            {isAccepting ? t("accepting") : t("accept")}
          </Button>
          <Button
            size="xs"
            variant="subtle"
            color="gray"
            leftSection={<IconX size={14} />}
            onClick={onDecline}
            loading={isDeclining}
            disabled={isAccepting}
          >
            {isDeclining ? t("declining") : t("decline")}
          </Button>
        </Group>
      </Stack>
    </Box>
  );
}

/** Invitation list section */
function InvitationsSection({
  invitationsState,
  onAcceptInvitation,
  onDeclineInvitation,
  acceptingId,
  decliningId,
}: {
  invitationsState: InvitationsState;
  onAcceptInvitation: (id: string) => void;
  onDeclineInvitation: (id: string) => void;
  acceptingId: string | null;
  decliningId: string | null;
}): React.ReactElement | null {
  const t = useTranslations("workspaces.invitations");

  if (invitationsState.type === "LOADING") {
    return null;
  }

  if (invitationsState.type === "ERROR") {
    return null;
  }

  const { invitations } = invitationsState;
  if (invitations.length === 0) {
    return null;
  }

  return (
    <>
      <Divider />
      <Stack gap="sm">
        <Text fw={600} size="sm">
          {t("sectionTitle")}
        </Text>
        {invitations.map((inv) => (
          <InvitationCard
            key={inv.id}
            invitation={inv}
            onAccept={() => onAcceptInvitation(inv.id)}
            onDecline={() => onDeclineInvitation(inv.id)}
            isAccepting={acceptingId === inv.id}
            isDeclining={decliningId === inv.id}
          />
        ))}
      </Stack>
    </>
  );
}

/** Workspace list form (pure UI) */
function WorkspacesListForm({
  state,
  invitationsState,
  onSelectWorkspace,
  onCreateWorkspace,
  onAcceptInvitation,
  onDeclineInvitation,
  acceptingId,
  decliningId,
}: {
  state: WorkspacesListState;
  invitationsState: InvitationsState;
  onSelectWorkspace: (handle: string) => void;
  onCreateWorkspace: () => void;
  onAcceptInvitation: (id: string) => void;
  onDeclineInvitation: (id: string) => void;
  acceptingId: string | null;
  decliningId: string | null;
}): React.ReactElement {
  const t = useTranslations("workspaces");

  if (state.type === "LOADING") {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (state.type === "ERROR") {
    return (
      <Stack gap="lg" align="center">
        <Text c="red" size="sm">
          {state.error}
        </Text>
        <Button onClick={onCreateWorkspace}>{t("list.createNew")}</Button>
      </Stack>
    );
  }

  const workspaces = state.workspaces;

  return (
    <Stack gap="lg">
      <Stack gap="xs" align="center">
        <Title order={2}>{t("list.headline")}</Title>
        <Text c="dimmed" size="sm">
          {t("list.description")}
        </Text>
      </Stack>

      {workspaces.length === 0 ? (
        <Text c="dimmed" ta="center" size="sm">
          {t("list.empty")}
        </Text>
      ) : (
        <Stack gap="sm">
          {workspaces.map((ws) => (
            <UnstyledButton
              key={ws.handle}
              onClick={() => onSelectWorkspace(ws.handle)}
              style={{
                border: "1px solid var(--mantine-color-default-border)",
                borderRadius: 12,
                padding: "12px 16px",
                transition: "background 0.15s ease",
                cursor: "pointer",
              }}
            >
              <Box>
                <Text fw={600} size="sm">
                  {ws.name}
                </Text>
                <Text c="dimmed" size="xs">
                  @{ws.handle}
                </Text>
              </Box>
            </UnstyledButton>
          ))}
        </Stack>
      )}

      <InvitationsSection
        invitationsState={invitationsState}
        onAcceptInvitation={onAcceptInvitation}
        onDeclineInvitation={onDeclineInvitation}
        acceptingId={acceptingId}
        decliningId={decliningId}
      />

      <Button
        variant="light"
        leftSection={<IconPlus size={16} />}
        onClick={onCreateWorkspace}
        fullWidth
      >
        {t("list.createNew")}
      </Button>
    </Stack>
  );
}

/** Container -> Component mapping (including FormPageLayout) */
export function WorkspacesList({
  state,
  invitationsState,
  onSelectWorkspace,
  onCreateWorkspace,
  onAcceptInvitation,
  onDeclineInvitation,
  acceptingId,
  decliningId,
}: WorkspacesListContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      <WorkspacesListForm
        state={state}
        invitationsState={invitationsState}
        onSelectWorkspace={onSelectWorkspace}
        onCreateWorkspace={onCreateWorkspace}
        onAcceptInvitation={onAcceptInvitation}
        onDeclineInvitation={onDeclineInvitation}
        acceptingId={acceptingId}
        decliningId={decliningId}
      />
    </FormPageLayout>
  );
}
