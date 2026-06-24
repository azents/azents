"use client";

import { Box, Center, Group, Loader, Table, Text, Title } from "@mantine/core";
import dayjs from "dayjs";
import type { UserListComponentProps } from "../containers/useUserListContainer";
import type { UserListState, UserResponse } from "../types";

function renderContent(
  state: UserListState,
  selectedUserId: string | null,
  onRowClick: (user: UserResponse) => void,
): React.ReactElement {
  switch (state.type) {
    case "LOADING":
      return (
        <Center p="xl">
          <Loader />
        </Center>
      );
    case "ERROR":
      return (
        <Center p="xl">
          <Text c="red">에러: {state.message}</Text>
        </Center>
      );
    case "LOADED":
      if (state.users.length === 0) {
        return (
          <Center p="xl">
            <Text c="dimmed">등록된 User가 없습니다.</Text>
          </Center>
        );
      }
      return (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>ID</Table.Th>
              <Table.Th>Primary Email</Table.Th>
              <Table.Th>생성일</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {state.users.map((user) => (
              <Table.Tr
                key={user.id}
                onClick={() => onRowClick(user)}
                style={{ cursor: "pointer" }}
                bg={
                  selectedUserId === user.id
                    ? "var(--mantine-primary-color-light)"
                    : ""
                }
              >
                <Table.Td>
                  <Text size="sm" ff="monospace" truncate>
                    {user.id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" truncate>
                    {user.primary_email}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {dayjs(user.created_at).format("YYYY-MM-DD")}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      );
  }
}

/**
 * User 목록 뷰 컴포넌트
 *
 * ADT 상태에 따라 적절한 UI를 렌더링합니다.
 */
export function UserListView({
  state,
  selectedUserId,
  onRowClick,
}: UserListComponentProps): React.ReactElement {
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Group p="md" justify="space-between">
        <Title order={5}>Users</Title>
      </Group>
      <Box style={{ flex: 1, overflow: "auto" }}>
        {renderContent(state, selectedUserId, onRowClick)}
      </Box>
    </Box>
  );
}
