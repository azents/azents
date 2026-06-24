"use client";

/**
 * Workspace member management UI component
 *
 * Displays member invitation form, member list, and pending invitation list.
 * Includes change role, delete member, and cancel invitation.
 */
import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Container,
  Group,
  Loader,
  NativeSelect,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useModals } from "@mantine/modals";
import { IconSend, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { WorkspaceMembersContainerProps } from "../containers/useWorkspaceMembers";
import type {
  InviteFormState,
  JoinRequestsState,
  MembersState,
  NotificationState,
  WorkspaceInvitation,
  WorkspaceInvitationsState,
  WorkspaceJoinRequest,
  WorkspaceMember,
} from "../types";

/** Role display label */
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

/** Role badge color */
function roleBadgeColor(role: string): string {
  if (role === "owner") {
    return "violet";
  }
  if (role === "manager") {
    return "blue";
  }
  return "gray";
}

/** Notification banner */
function NotificationBanner({
  notification,
  onClear,
}: {
  notification: NotificationState | null;
  onClear: () => void;
}): React.ReactElement | null {
  const t = useTranslations("workspace.dashboard");

  if (notification === null) {
    return null;
  }

  return (
    <Alert
      color={notification.type === "success" ? "green" : "red"}
      withCloseButton
      onClose={onClear}
    >
      {t(notification.message)}
    </Alert>
  );
}

/** Member invitation form */
function InviteForm({
  inviteFormState,
  onInvite,
  onClearInviteStatus,
}: {
  inviteFormState: InviteFormState;
  onInvite: (email: string, role: "member" | "manager") => void;
  onClearInviteStatus: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.dashboard");

  const form = useForm({
    mode: "controlled",
    initialValues: {
      email: "",
      role: "member" as "member" | "manager",
    },
    validate: {
      email: (value) => (value.trim() ? null : t("inviteEmailRequired")),
    },
  });

  const isSending = inviteFormState.type === "SENDING";
  const error = inviteFormState.type === "IDLE" ? inviteFormState.error : null;
  const success =
    inviteFormState.type === "IDLE" ? inviteFormState.success : null;

  function handleSubmit(values: typeof form.values): void {
    onInvite(values.email.trim(), values.role);
    form.reset();
  }

  return (
    <Box
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: 12,
        padding: "20px",
      }}
    >
      <Stack gap="md">
        <Text fw={600} size="sm">
          {t("inviteSection")}
        </Text>

        {success && (
          <Alert color="green" withCloseButton onClose={onClearInviteStatus}>
            {t(success)}
          </Alert>
        )}
        {error && (
          <Alert color="red" withCloseButton onClose={onClearInviteStatus}>
            {t(error)}
          </Alert>
        )}

        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack gap="sm" hiddenFrom="sm">
            <TextInput
              placeholder={t("inviteEmailPlaceholder")}
              type="email"
              {...form.getInputProps("email")}
              disabled={isSending}
            />
            <Group gap="sm" align="flex-end">
              <NativeSelect
                flex={1}
                label={t("inviteRoleLabel")}
                {...form.getInputProps("role")}
                data={[
                  { value: "member", label: t("roleMember") },
                  { value: "manager", label: t("roleManager") },
                ]}
                disabled={isSending}
              />
              <Button
                type="submit"
                leftSection={<IconSend size={16} />}
                loading={isSending}
              >
                {t("inviteSubmit")}
              </Button>
            </Group>
          </Stack>
          <Group gap="sm" align="flex-end" visibleFrom="sm">
            <TextInput
              flex={1}
              placeholder={t("inviteEmailPlaceholder")}
              type="email"
              {...form.getInputProps("email")}
              disabled={isSending}
            />
            <NativeSelect
              label={t("inviteRoleLabel")}
              {...form.getInputProps("role")}
              data={[
                { value: "member", label: t("roleMember") },
                { value: "manager", label: t("roleManager") },
              ]}
              disabled={isSending}
            />
            <Button
              type="submit"
              leftSection={<IconSend size={16} />}
              loading={isSending}
            >
              {t("inviteSubmit")}
            </Button>
          </Group>
        </form>
      </Stack>
    </Box>
  );
}

/** Member row component */
function MemberRow({
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
}): React.ReactElement {
  const t = useTranslations("workspace.dashboard");
  const modals = useModals();
  const roleLabel = useRoleLabel(member.role);
  const isOwner = member.role === "owner";
  // Management control condition: manager+ permission && not self && target is not owner
  const showControls = canManage && !isCurrentUser && !isOwner;

  return (
    <Table.Tr>
      <Table.Td>
        <Group gap="xs">
          <Text size="sm" fw={500}>
            {member.name}
          </Text>
          {isCurrentUser && (
            <Badge variant="outline" size="xs" color="gray">
              {t("you")}
            </Badge>
          )}
        </Group>
      </Table.Td>
      <Table.Td>
        <Badge variant="light" color={roleBadgeColor(member.role)} size="sm">
          {roleLabel}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed">
          {new Date(member.created_at).toLocaleDateString()}
        </Text>
      </Table.Td>
      {canManage && (
        <Table.Td>
          {showControls && (
            <Group gap="xs">
              <NativeSelect
                size="xs"
                value={member.role}
                data={[
                  { value: "member", label: t("roleMember") },
                  { value: "manager", label: t("roleManager") },
                ]}
                onChange={(e) =>
                  onUpdateRole(
                    member.id,
                    e.currentTarget.value as "manager" | "member",
                  )
                }
                style={{ width: 120 }}
              />
              <Button
                size="xs"
                variant="subtle"
                color="red"
                leftSection={<IconTrash size={14} />}
                onClick={() => {
                  modals.openConfirmModal({
                    title: t("removeMember"),
                    children: t("removeMemberConfirm"),
                    labels: { confirm: t("removeMember"), cancel: t("cancel") },
                    confirmProps: { color: "red" },
                    onConfirm: () => onRemoveMember(member.id),
                  });
                }}
              >
                {t("removeMember")}
              </Button>
            </Group>
          )}
        </Table.Td>
      )}
    </Table.Tr>
  );
}

/** Member list section */
function MemberListSection({
  membersState,
  currentWorkspaceUserId,
  canManage,
  onUpdateRole,
  onRemoveMember,
}: {
  membersState: MembersState;
  currentWorkspaceUserId: string | null;
  canManage: boolean;
  onUpdateRole: (
    workspaceUserId: string,
    role: "owner" | "manager" | "member",
  ) => void;
  onRemoveMember: (workspaceUserId: string) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.dashboard");

  return (
    <Box
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: 12,
        padding: "20px",
      }}
    >
      <Stack gap="md">
        <Text fw={600} size="sm">
          {t("memberListSection")}
        </Text>

        {membersState.type === "LOADING" && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}

        {membersState.type === "ERROR" && (
          <Text c="dimmed" size="sm" ta="center">
            {t("inviteError")}
          </Text>
        )}

        {membersState.type === "READY" && membersState.members.length === 0 && (
          <Text c="dimmed" size="sm" ta="center">
            {t("noMembers")}
          </Text>
        )}

        {membersState.type === "READY" && membersState.members.length > 0 && (
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("memberName")}</Table.Th>
                <Table.Th>{t("memberRole")}</Table.Th>
                <Table.Th>{t("joinedAt")}</Table.Th>
                {canManage && <Table.Th>{t("memberActions")}</Table.Th>}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {membersState.members.map((member) => (
                <MemberRow
                  key={member.id}
                  member={member}
                  isCurrentUser={member.id === currentWorkspaceUserId}
                  canManage={canManage}
                  onUpdateRole={onUpdateRole}
                  onRemoveMember={onRemoveMember}
                />
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Box>
  );
}

/** Invitation row component */
function InvitationRow({
  invitation,
  canManage,
  onCancel,
}: {
  invitation: WorkspaceInvitation;
  canManage: boolean;
  onCancel: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.dashboard");
  const modals = useModals();
  const roleLabel = useRoleLabel(invitation.role);

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm">{invitation.email}</Text>
      </Table.Td>
      <Table.Td>
        <Badge
          variant="light"
          color={roleBadgeColor(invitation.role)}
          size="sm"
        >
          {roleLabel}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed">
          {new Date(invitation.created_at).toLocaleDateString()}
        </Text>
      </Table.Td>
      {canManage && (
        <Table.Td>
          <Button
            size="xs"
            variant="subtle"
            color="red"
            leftSection={<IconTrash size={14} />}
            onClick={() => {
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
            }}
          >
            {t("cancelInvitation")}
          </Button>
        </Table.Td>
      )}
    </Table.Tr>
  );
}

/** Pending invitation list section */
function PendingInvitationsSection({
  invitationsState,
  canManage,
  onCancelInvitation,
}: {
  invitationsState: WorkspaceInvitationsState;
  canManage: boolean;
  onCancelInvitation: (invitationId: string) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.dashboard");

  return (
    <Box
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: 12,
        padding: "20px",
      }}
    >
      <Stack gap="md">
        <Text fw={600} size="sm">
          {t("pendingInvitationsSection")}
        </Text>

        {invitationsState.type === "LOADING" && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}

        {invitationsState.type === "ERROR" && (
          <Text c="dimmed" size="sm" ta="center">
            {t("inviteError")}
          </Text>
        )}

        {invitationsState.type === "READY" &&
          invitationsState.invitations.length === 0 && (
            <Text c="dimmed" size="sm" ta="center">
              {t("noPendingInvitations")}
            </Text>
          )}

        {invitationsState.type === "READY" &&
          invitationsState.invitations.length > 0 && (
            <Table highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("inviteEmailPlaceholder")}</Table.Th>
                  <Table.Th>{t("memberRole")}</Table.Th>
                  <Table.Th>{t("invitedAt")}</Table.Th>
                  {canManage && <Table.Th>{t("memberActions")}</Table.Th>}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {invitationsState.invitations.map((inv) => (
                  <InvitationRow
                    key={inv.id}
                    invitation={inv}
                    canManage={canManage}
                    onCancel={() => onCancelInvitation(inv.id)}
                  />
                ))}
              </Table.Tbody>
            </Table>
          )}
      </Stack>
    </Box>
  );
}

/** Join request row component */
function JoinRequestRow({
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
}): React.ReactElement {
  const t = useTranslations("workspace.dashboard");
  const modals = useModals();

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm">{joinRequest.user_id.slice(0, 8)}</Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {joinRequest.message ?? "-"}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed">
          {new Date(joinRequest.created_at).toLocaleDateString()}
        </Text>
      </Table.Td>
      <Table.Td>
        <Group gap="xs">
          <Button
            size="xs"
            variant="subtle"
            color="green"
            onClick={() => {
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
            }}
          >
            {t("approveRequest")}
          </Button>
          <Button
            size="xs"
            variant="subtle"
            color="red"
            onClick={() => {
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
            }}
          >
            {t("rejectRequest")}
          </Button>
          <Button size="xs" variant="subtle" color="gray" onClick={onMute}>
            {t("muteRequest")}
          </Button>
          <Button
            size="xs"
            variant="subtle"
            color="red"
            onClick={() => {
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
            }}
          >
            {t("deleteRequest")}
          </Button>
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}

/** Join request list section */
function JoinRequestsSection({
  joinRequestsState,
  onApproveJoinRequest,
  onRejectJoinRequest,
  onMuteJoinRequest,
  onDeleteJoinRequest,
}: {
  joinRequestsState: JoinRequestsState;
  onApproveJoinRequest: (joinRequestId: string) => void;
  onRejectJoinRequest: (joinRequestId: string) => void;
  onMuteJoinRequest: (joinRequestId: string) => void;
  onDeleteJoinRequest: (joinRequestId: string) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.dashboard");

  return (
    <Box
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: 12,
        padding: "20px",
      }}
    >
      <Stack gap="md">
        <Text fw={600} size="sm">
          {t("joinRequestsSection")}
        </Text>

        {joinRequestsState.type === "LOADING" && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}

        {joinRequestsState.type === "ERROR" && (
          <Text c="dimmed" size="sm" ta="center">
            {t("inviteError")}
          </Text>
        )}

        {joinRequestsState.type === "READY" &&
          joinRequestsState.joinRequests.length === 0 && (
            <Text c="dimmed" size="sm" ta="center">
              {t("noJoinRequests")}
            </Text>
          )}

        {joinRequestsState.type === "READY" &&
          joinRequestsState.joinRequests.length > 0 && (
            <Table highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>User</Table.Th>
                  <Table.Th>{t("requestMessage")}</Table.Th>
                  <Table.Th>{t("requestedAt")}</Table.Th>
                  <Table.Th>{t("memberActions")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {joinRequestsState.joinRequests.map((jr) => (
                  <JoinRequestRow
                    key={jr.id}
                    joinRequest={jr}
                    onApprove={() => onApproveJoinRequest(jr.id)}
                    onReject={() => onRejectJoinRequest(jr.id)}
                    onMute={() => onMuteJoinRequest(jr.id)}
                    onDelete={() => onDeleteJoinRequest(jr.id)}
                  />
                ))}
              </Table.Tbody>
            </Table>
          )}
      </Stack>
    </Box>
  );
}

/** Workspace member management main UI */
export function WorkspaceMembersView({
  currentWorkspaceUserId,
  currentRole,
  inviteFormState,
  membersState,
  invitationsState,
  joinRequestsState,
  notification,
  onInvite,
  onClearInviteStatus,
  onUpdateRole,
  onRemoveMember,
  onCancelInvitation,
  onApproveJoinRequest,
  onRejectJoinRequest,
  onMuteJoinRequest,
  onDeleteJoinRequest,
  onClearNotification,
}: WorkspaceMembersContainerProps): React.ReactElement {
  // Show management controls only with manager or higher permission
  const canManage = currentRole === "owner" || currentRole === "manager";

  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <NotificationBanner
          notification={notification}
          onClear={onClearNotification}
        />

        {canManage && (
          <InviteForm
            inviteFormState={inviteFormState}
            onInvite={onInvite}
            onClearInviteStatus={onClearInviteStatus}
          />
        )}

        <MemberListSection
          membersState={membersState}
          currentWorkspaceUserId={currentWorkspaceUserId}
          canManage={canManage}
          onUpdateRole={onUpdateRole}
          onRemoveMember={onRemoveMember}
        />

        <PendingInvitationsSection
          invitationsState={invitationsState}
          canManage={canManage}
          onCancelInvitation={onCancelInvitation}
        />

        {canManage && (
          <JoinRequestsSection
            joinRequestsState={joinRequestsState}
            onApproveJoinRequest={onApproveJoinRequest}
            onRejectJoinRequest={onRejectJoinRequest}
            onMuteJoinRequest={onMuteJoinRequest}
            onDeleteJoinRequest={onDeleteJoinRequest}
          />
        )}
      </Stack>
    </Container>
  );
}
