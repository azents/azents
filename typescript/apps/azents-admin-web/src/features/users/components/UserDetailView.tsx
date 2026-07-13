"use client";

import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconPlus,
  IconShieldCheck,
  IconShieldOff,
  IconTrash,
} from "@tabler/icons-react";
import dayjs from "dayjs";
import { useState } from "react";
import type { UserDetailComponentProps } from "../containers/useUserDetailContainer";
import type { SystemAdminRoleState, UserEmailResponse } from "../types";

/**
 * 이메일 목록 서브섹션
 */
function EmailSection({
  emails,
  isLoading,
  onAddEmail,
  onDeleteEmail,
}: {
  emails: UserEmailResponse[];
  isLoading: boolean;
  onAddEmail: (email: string) => void;
  onDeleteEmail: (emailId: string) => void;
}): React.ReactElement {
  const [newEmail, setNewEmail] = useState("");

  const handleSubmit = (): void => {
    if (!newEmail.trim()) {
      return;
    }
    onAddEmail(newEmail.trim());
    setNewEmail("");
  };

  return (
    <Stack gap="sm">
      <Title order={6}>Emails</Title>
      {isLoading ? (
        <Center p="sm">
          <Loader size="sm" />
        </Center>
      ) : emails.length === 0 ? (
        <Text size="sm" c="dimmed">
          등록된 이메일이 없습니다.
        </Text>
      ) : (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>이메일</Table.Th>
              <Table.Th>인증 상태</Table.Th>
              <Table.Th w={60} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {emails.map((email) => (
              <Table.Tr key={email.id}>
                <Table.Td>
                  <Text size="sm">{email.email}</Text>
                </Table.Td>
                <Table.Td>
                  {email.verified_at ? (
                    <Badge color="green" variant="light" size="sm">
                      인증됨
                    </Badge>
                  ) : (
                    <Badge color="gray" variant="light" size="sm">
                      대기중
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  <ActionIcon
                    color="red"
                    variant="subtle"
                    size="sm"
                    onClick={() => onDeleteEmail(email.id)}
                    title="이메일 삭제"
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Group gap="xs">
        <TextInput
          placeholder="새 이메일 주소"
          size="xs"
          value={newEmail}
          onChange={(e) => setNewEmail(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSubmit();
            }
          }}
          style={{ flex: 1 }}
        />
        <Button
          size="xs"
          variant="light"
          leftSection={<IconPlus size={14} />}
          onClick={handleSubmit}
          disabled={!newEmail.trim()}
        >
          추가
        </Button>
      </Group>
    </Stack>
  );
}

function SystemAdminSection({
  state,
  onGrant,
  onRevoke,
}: {
  state: SystemAdminRoleState;
  onGrant: () => void;
  onRevoke: () => void;
}): React.ReactElement {
  if (state.type === "LOADING") {
    return (
      <Stack gap="sm">
        <Title order={6}>System administrator</Title>
        <Loader size="sm" />
      </Stack>
    );
  }

  if (state.type === "ERROR") {
    return (
      <Stack gap="sm">
        <Title order={6}>System administrator</Title>
        <Alert
          color="red"
          variant="light"
          icon={<IconAlertCircle size={16} />}
          title="Role status unavailable"
        >
          {state.message}
        </Alert>
      </Stack>
    );
  }

  const processing = state.action !== "IDLE";
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start">
        <Stack gap="xs">
          <Title order={6}>System administrator</Title>
          <Text size="sm" c="dimmed">
            Controls instance-wide access to Admin Web and Admin API operations.
          </Text>
        </Stack>
        <Group gap="xs">
          <Badge color={state.assigned ? "blue" : "gray"} variant="light">
            {state.assigned ? "Granted" : "Not granted"}
          </Badge>
          {state.currentUser && (
            <Badge color="teal" variant="light">
              Current session
            </Badge>
          )}
        </Group>
      </Group>

      {state.assigned ? (
        <Stack gap="xs" align="flex-start">
          <Button
            color="red"
            variant="outline"
            leftSection={<IconShieldOff size={16} />}
            onClick={onRevoke}
            loading={state.action === "REVOKING"}
            disabled={processing || state.finalAdmin}
          >
            Revoke system administrator
          </Button>
          {state.finalAdmin && (
            <Text size="xs" c="orange">
              This is the final system administrator. Grant another user before
              revoking this role.
            </Text>
          )}
        </Stack>
      ) : (
        <Button
          variant="light"
          leftSection={<IconShieldCheck size={16} />}
          onClick={onGrant}
          loading={state.action === "GRANTING"}
          disabled={processing}
          style={{ alignSelf: "flex-start" }}
        >
          Grant system administrator
        </Button>
      )}
    </Stack>
  );
}

/**
 * User 상세 뷰 컴포넌트
 *
 * ADT 상태에 따라 유저 정보 또는 플레이스홀더를 렌더링합니다.
 */
export function UserDetailView({
  state,
  roleState,
  emails,
  isLoadingEmails,
  onDelete,
  onGrantAdmin,
  onRevokeAdmin,
  onAddEmail,
  onDeleteEmail,
}: UserDetailComponentProps): React.ReactElement {
  switch (state.type) {
    case "EMPTY":
      return (
        <Center h="100%">
          <Text c="dimmed">User를 선택하세요.</Text>
        </Center>
      );

    case "LOADING":
      return (
        <Center h="100%">
          <Loader />
        </Center>
      );

    case "ERROR":
      return (
        <Center h="100%">
          <Text c="red">에러: {state.message}</Text>
        </Center>
      );

    case "VIEWING":
    case "DELETING": {
      const user = state.user;
      const isProcessing = state.type === "DELETING";
      const deleteBlockedByFinalAdmin =
        roleState.type === "READY" && roleState.finalAdmin;

      return (
        <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
          <Group p="sm" justify="space-between">
            <Title order={5}>User 상세</Title>
          </Group>

          <Box style={{ flex: 1, overflow: "auto" }} p="md">
            <Stack gap="lg">
              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  ID
                </Text>
                <Text size="sm" ff="monospace">
                  {user.id}
                </Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  Primary Email
                </Text>
                <Text size="sm">{user.primary_email}</Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  생성일
                </Text>
                <Text size="sm">
                  {dayjs(user.created_at).format("YYYY-MM-DD HH:mm:ss")}
                </Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  수정일
                </Text>
                <Text size="sm">
                  {dayjs(user.updated_at).format("YYYY-MM-DD HH:mm:ss")}
                </Text>
              </Stack>

              <SystemAdminSection
                state={roleState}
                onGrant={onGrantAdmin}
                onRevoke={onRevokeAdmin}
              />

              <EmailSection
                emails={emails}
                isLoading={isLoadingEmails}
                onAddEmail={onAddEmail}
                onDeleteEmail={onDeleteEmail}
              />

              <Stack mt="xl" gap="xs" align="flex-start">
                <Button
                  color="red"
                  variant="outline"
                  leftSection={<IconTrash size={16} />}
                  onClick={onDelete}
                  loading={isProcessing}
                  disabled={isProcessing || deleteBlockedByFinalAdmin}
                >
                  {isProcessing ? "삭제 처리 중..." : "삭제"}
                </Button>
                {deleteBlockedByFinalAdmin && (
                  <Text size="xs" c="orange">
                    The final system administrator cannot be deleted. Grant
                    another administrator first.
                  </Text>
                )}
              </Stack>
            </Stack>
          </Box>
        </Box>
      );
    }
  }
}
