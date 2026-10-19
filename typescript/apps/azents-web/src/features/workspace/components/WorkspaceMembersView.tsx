"use client";
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
  rem,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconSend, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
/**
 * Workspace member management UI component
 *
 * Displays member invitation form, member list, and pending invitation list.
 * Includes change role, delete member, and cancel invitation.
 */
import { formatLocalizedDate } from "@/shared/lib/date-format";

import { useInvitationRowController } from "../containers/useInvitationRowController";
import { useInviteFormController } from "../containers/useInviteFormController";
import { useJoinRequestRowController } from "../containers/useJoinRequestRowController";
import { useMemberRowController } from "../containers/useMemberRowController";

import type { InvitationRowViewProps } from "../containers/useInvitationRowController";
import type { InviteFormViewProps } from "../containers/useInviteFormController";
import type { JoinRequestRowViewProps } from "../containers/useJoinRequestRowController";
import type { MemberRowViewProps } from "../containers/useMemberRowController";
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
function InviteForm(props: {
  inviteFormState: InviteFormState;
  onInvite: (email: string, role: "member" | "manager") => void;
  onClearInviteStatus: () => void;
}): React.ReactElement {
  return <InviteFormView {...useInviteFormController(props)} />;
}

export function InviteFormView({
  onClearInviteStatus,
  t,
  form,
  isSending,
  error,
  success,
  handleSubmit,
}: InviteFormViewProps): React.ReactElement {
  return (
    <Box
      style={{
        border: `${rem(1)} solid var(--mantine-color-default-border)`,
        borderRadius: "var(--mantine-radius-md)",
        padding: "var(--mantine-spacing-lg)",
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
function MemberRow(props: {
  member: WorkspaceMember;
  isCurrentUser: boolean;
  canManage: boolean;
  onUpdateRole: (
    workspaceUserId: string,
    role: "owner" | "manager" | "member",
  ) => void;
  onRemoveMember: (workspaceUserId: string) => void;
}): React.ReactElement {
  return <MemberRowView {...useMemberRowController(props)} />;
}

export function MemberRowView({
  member,
  isCurrentUser,
  canManage,
  onUpdateRole,
  t,
  locale,
  roleLabel,
  showControls,
  confirmMemberAction1,
}: MemberRowViewProps): React.ReactElement {
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
          {formatLocalizedDate(new Date(member.created_at), locale)}
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
                onChange={(e) => {
                  const role = e.currentTarget.value;
                  if (role === "manager" || role === "member") {
                    onUpdateRole(member.id, role);
                  }
                }}
                style={{ width: 120 }}
              />
              <Button
                size="xs"
                variant="subtle"
                color="red"
                leftSection={<IconTrash size={14} />}
                onClick={() => confirmMemberAction1()}
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
        border: `${rem(1)} solid var(--mantine-color-default-border)`,
        borderRadius: "var(--mantine-radius-md)",
        padding: "var(--mantine-spacing-lg)",
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
function InvitationRow(props: {
  invitation: WorkspaceInvitation;
  canManage: boolean;
  onCancel: () => void;
}): React.ReactElement {
  return <InvitationRowView {...useInvitationRowController(props)} />;
}

export function InvitationRowView({
  invitation,
  canManage,
  t,
  locale,
  roleLabel,
  confirmInvitationAction1,
}: InvitationRowViewProps): React.ReactElement {
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
          {formatLocalizedDate(new Date(invitation.created_at), locale)}
        </Text>
      </Table.Td>
      {canManage && (
        <Table.Td>
          <Button
            size="xs"
            variant="subtle"
            color="red"
            leftSection={<IconTrash size={14} />}
            onClick={() => confirmInvitationAction1()}
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
        border: `${rem(1)} solid var(--mantine-color-default-border)`,
        borderRadius: "var(--mantine-radius-md)",
        padding: "var(--mantine-spacing-lg)",
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
function JoinRequestRow(props: {
  joinRequest: WorkspaceJoinRequest;
  onApprove: () => void;
  onReject: () => void;
  onMute: () => void;
  onDelete: () => void;
}): React.ReactElement {
  return <JoinRequestRowView {...useJoinRequestRowController(props)} />;
}

export function JoinRequestRowView({
  joinRequest,
  onMute,
  t,
  locale,
  confirmJoinRequestAction1,
  confirmJoinRequestAction2,
  confirmJoinRequestAction3,
}: JoinRequestRowViewProps): React.ReactElement {
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
          {formatLocalizedDate(new Date(joinRequest.created_at), locale)}
        </Text>
      </Table.Td>
      <Table.Td>
        <Group gap="xs">
          <Button
            size="xs"
            variant="subtle"
            color="green"
            onClick={() => confirmJoinRequestAction1()}
          >
            {t("approveRequest")}
          </Button>
          <Button
            size="xs"
            variant="subtle"
            color="red"
            onClick={() => confirmJoinRequestAction2()}
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
            onClick={() => confirmJoinRequestAction3()}
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
        border: `${rem(1)} solid var(--mantine-color-default-border)`,
        borderRadius: "var(--mantine-radius-md)",
        padding: "var(--mantine-spacing-lg)",
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
