"use client";

import {
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import type { WorkspaceDetailComponentProps } from "../containers/useWorkspaceDetailContainer";

/**
 * Workspace detail view component
 *
 * Renders a form or placeholder for the current ADT state.
 */
export function WorkspaceDetailView({
  state,
  form,
  isDirty,
  onSubmit,
  onCancel,
}: WorkspaceDetailComponentProps): React.ReactElement {
  switch (state.type) {
    case "EMPTY":
      return (
        <Center h="100%">
          <Text c="dimmed">Select a workspace or create a new one.</Text>
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
          <Text c="red">Error: {state.message}</Text>
        </Center>
      );

    case "EDITING":
    case "SAVING": {
      const isSaving = state.type === "SAVING";
      const isProcessing = isSaving;
      const isNew = state.isNew;
      const workspace = state.workspace;

      return (
        <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
          <form
            onSubmit={form.onSubmit(onSubmit)}
            style={{ display: "flex", flexDirection: "column", height: "100%" }}
          >
            <Group p="sm" justify="space-between">
              <Title order={5}>
                {isNew ? "Add Workspace" : "Edit Workspace"}
              </Title>
              <Group gap="xs">
                <Button
                  variant="outline"
                  size="xs"
                  onClick={onCancel}
                  disabled={isProcessing}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  size="xs"
                  disabled={isProcessing || (!isNew && !isDirty)}
                  loading={isSaving}
                >
                  {isSaving ? "Saving..." : "Save"}
                </Button>
              </Group>
            </Group>

            <Box style={{ flex: 1, overflow: "auto" }} p="md">
              <Stack gap="md">
                <TextInput
                  label="Name"
                  placeholder="Workspace name"
                  required
                  key={form.key("name")}
                  {...form.getInputProps("name")}
                />
                <TextInput
                  label="Handle"
                  placeholder="workspace-handle"
                  description="Use lowercase letters, numbers, and hyphens only."
                  required
                  key={form.key("handle")}
                  {...form.getInputProps("handle")}
                />
                {workspace && !isNew && (
                  <Stack gap="xs">
                    <Text size="sm" c="dimmed">
                      Created At:{" "}
                      {dayjs(workspace.created_at).format(
                        "YYYY-MM-DD HH:mm:ss",
                      )}
                    </Text>
                    <Text size="sm" c="dimmed">
                      Updated At:{" "}
                      {dayjs(workspace.updated_at).format(
                        "YYYY-MM-DD HH:mm:ss",
                      )}
                    </Text>
                  </Stack>
                )}
              </Stack>
            </Box>
          </form>
        </Box>
      );
    }
  }
}
