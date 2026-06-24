"use client";

import {
  Badge,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import dayjs from "dayjs";
import type { WorkspaceMemberDetailComponentProps } from "../containers/useWorkspaceMemberDetailContainer";

/**
 * WorkspaceMember 상세 뷰 컴포넌트
 *
 * ADT 상태에 따라 멤버 정보 또는 플레이스홀더를 렌더링합니다.
 */
export function WorkspaceMemberDetailView({
  state,
  onDelete,
}: WorkspaceMemberDetailComponentProps): React.ReactElement {
  switch (state.type) {
    case "EMPTY":
      return (
        <Center h="100%">
          <Text c="dimmed">멤버를 선택하세요.</Text>
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
      const member = state.member;
      const isProcessing = state.type === "DELETING";

      return (
        <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
          <Group p="sm" justify="space-between">
            <Title order={5}>멤버 상세</Title>
          </Group>

          <Box style={{ flex: 1, overflow: "auto" }} p="md">
            <Stack gap="lg">
              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  ID
                </Text>
                <Text size="sm" ff="monospace">
                  {member.id}
                </Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  User ID
                </Text>
                <Text size="sm" ff="monospace">
                  {member.user_id}
                </Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  Workspace ID
                </Text>
                <Text size="sm" ff="monospace">
                  {member.workspace_id}
                </Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  이름
                </Text>
                <Text>{member.name}</Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  로케일
                </Text>
                <Badge variant="light">{member.locale}</Badge>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  역할
                </Text>
                <Badge variant="light">{member.role}</Badge>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  가입일
                </Text>
                <Text size="sm">
                  {dayjs(member.created_at).format("YYYY-MM-DD HH:mm:ss")}
                </Text>
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={500} c="dimmed">
                  수정일
                </Text>
                <Text size="sm">
                  {dayjs(member.updated_at).format("YYYY-MM-DD HH:mm:ss")}
                </Text>
              </Stack>

              <Box mt="xl">
                <Button
                  color="red"
                  variant="outline"
                  leftSection={<IconTrash size={16} />}
                  onClick={onDelete}
                  loading={isProcessing}
                  disabled={isProcessing}
                >
                  {isProcessing ? "제거 중..." : "멤버 제거"}
                </Button>
              </Box>
            </Stack>
          </Box>
        </Box>
      );
    }
  }
}
