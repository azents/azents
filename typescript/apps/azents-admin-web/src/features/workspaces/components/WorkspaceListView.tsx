"use client";

import {
  Badge,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import type { WorkspaceListComponentProps } from "../containers/useWorkspaceListContainer";
import type { WorkspaceListState, WorkspaceResponse } from "../types";

function renderContent(
  state: WorkspaceListState,
  selectedWorkspaceHandle: string | null,
  onRowClick: (workspace: WorkspaceResponse) => void,
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
          <Text c="red">Error: {state.message}</Text>
        </Center>
      );
    case "LOADED":
      if (state.workspaces.length === 0) {
        return (
          <Center p="xl">
            <Text c="dimmed">No workspaces found.</Text>
          </Center>
        );
      }
      return (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Handle</Table.Th>
              <Table.Th>Name</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {state.workspaces.map((workspace) => (
              <Table.Tr
                key={workspace.handle}
                onClick={() => onRowClick(workspace)}
                style={{ cursor: "pointer" }}
                bg={
                  selectedWorkspaceHandle === workspace.handle
                    ? "var(--mantine-primary-color-light)"
                    : ""
                }
              >
                <Table.Td>
                  <Badge variant="light">{workspace.handle}</Badge>
                </Table.Td>
                <Table.Td>{workspace.name}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      );
  }
}

/**
 * Workspace list view component
 *
 * Renders the appropriate UI for the current ADT state.
 */
export function WorkspaceListView({
  state,
  selectedWorkspaceHandle,
  onRowClick,
  onCreateNew,
}: WorkspaceListComponentProps): React.ReactElement {
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Group p="md" justify="space-between">
        <Title order={5}>Workspaces</Title>
        <Button
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={onCreateNew}
        >
          Add Workspace
        </Button>
      </Group>
      <Box style={{ flex: 1, overflow: "auto" }}>
        {renderContent(state, selectedWorkspaceHandle, onRowClick)}
      </Box>
    </Box>
  );
}
