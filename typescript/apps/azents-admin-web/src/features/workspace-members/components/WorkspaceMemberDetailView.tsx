"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconCrown, IconTrash } from "@tabler/icons-react";
import dayjs from "dayjs";
import type { WorkspaceMemberDetailComponentProps } from "../containers/useWorkspaceMemberDetailContainer";

/** Render the Workspace member create and administration inspector. */
export function WorkspaceMemberDetailView({
  state,
  form,
  userOptions,
  roleOptions,
  isDirty,
  actionError,
  onSubmit,
  onCancel,
  onDelete,
  onTransferOwnership,
}: WorkspaceMemberDetailComponentProps): React.ReactElement {
  switch (state.type) {
    case "EMPTY":
      return (
        <Center h="100%">
          <Text c="dimmed">Select a member or add a new one.</Text>
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
        <Center h="100%" p="md">
          <Alert color="red" title="Unable to load Workspace member">
            {state.message}
          </Alert>
        </Center>
      );

    case "EDITING":
    case "SAVING":
    case "TRANSFERRING":
    case "DELETING": {
      const isFormState = state.type === "EDITING" || state.type === "SAVING";
      const member = state.member;
      const isNew = isFormState ? state.isNew : false;
      const ownerExists = isFormState ? state.ownerExists : true;
      const isOwner = member?.role === "owner";
      const isSaving = state.type === "SAVING";
      const isTransferring = state.type === "TRANSFERRING";
      const isDeleting = state.type === "DELETING";
      const isProcessing = isSaving || isTransferring || isDeleting;

      return (
        <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
          <form
            onSubmit={form.onSubmit(onSubmit)}
            style={{ display: "flex", flexDirection: "column", height: "100%" }}
          >
            <Group p="sm" justify="space-between">
              <Title order={5}>
                {isNew ? "Add Workspace Member" : "Manage Workspace Member"}
              </Title>
              <Group gap="xs">
                <Button
                  variant="outline"
                  size="xs"
                  onClick={onCancel}
                  disabled={isProcessing || (!isNew && !isDirty)}
                >
                  {isNew ? "Cancel" : "Reset"}
                </Button>
                <Button
                  type="submit"
                  size="xs"
                  loading={isSaving}
                  disabled={
                    isProcessing ||
                    (!isNew && !isDirty) ||
                    (isNew && userOptions.length === 0)
                  }
                >
                  {isNew ? "Add Member" : "Save Changes"}
                </Button>
              </Group>
            </Group>

            <Box style={{ flex: 1, overflow: "auto" }} p="md">
              <Stack gap="md">
                {actionError && (
                  <Alert color="red" title="Operation failed">
                    {actionError}
                  </Alert>
                )}

                {isNew && userOptions.length === 0 && (
                  <Alert color="yellow" title="No available Users">
                    Every User already belongs to this Workspace, or no global
                    Users are available.
                  </Alert>
                )}

                {isNew ? (
                  <Select
                    label="User"
                    description="Choose an existing global User to add to this Workspace."
                    placeholder="Search by email or User ID"
                    data={userOptions}
                    searchable
                    required
                    disabled={isProcessing}
                    key={form.key("userId")}
                    {...form.getInputProps("userId")}
                  />
                ) : (
                  <Stack gap="xs">
                    <Text size="sm" fw={500} c="dimmed">
                      User ID
                    </Text>
                    <Text size="sm" ff="monospace">
                      {member?.user_id}
                    </Text>
                  </Stack>
                )}

                <TextInput
                  label="Workspace display name"
                  description="This name is shown only inside this Workspace."
                  placeholder="Member name"
                  required
                  disabled={isProcessing}
                  key={form.key("name")}
                  {...form.getInputProps("name")}
                />

                <Select
                  label="Workspace role"
                  description={
                    isOwner
                      ? "Transfer ownership before changing the current Owner role."
                      : "Owner assignment for existing members uses Transfer Ownership."
                  }
                  data={roleOptions}
                  required
                  disabled={isProcessing || isOwner}
                  key={form.key("role")}
                  {...form.getInputProps("role")}
                />

                {isNew && ownerExists && (
                  <Alert
                    color="blue"
                    title="This Workspace already has an Owner"
                  >
                    Add the User as a Manager or Member. To make them Owner,
                    create the membership first and then transfer ownership from
                    their member details.
                  </Alert>
                )}

                {!isNew && isOwner && (
                  <Alert color="blue" title="Owner protections are active">
                    The current Owner cannot be demoted or removed directly.
                    Transfer ownership to another member first.
                  </Alert>
                )}

                {!isNew && member && !isOwner && (
                  <>
                    <Divider label="Ownership" labelPosition="left" />
                    <Stack gap="xs">
                      <Text size="sm" c="dimmed">
                        Make this member the Workspace Owner. The current Owner
                        will become a Manager.
                      </Text>
                      <Button
                        variant="light"
                        leftSection={<IconCrown size={16} />}
                        onClick={onTransferOwnership}
                        loading={isTransferring}
                        disabled={isProcessing}
                      >
                        Transfer Ownership to This Member
                      </Button>
                    </Stack>
                  </>
                )}

                {!isNew && member && (
                  <>
                    <Divider label="Membership" labelPosition="left" />
                    <Group justify="space-between" align="flex-start">
                      <Stack gap="xs">
                        <Group gap="xs">
                          <Badge variant="light">{member.role}</Badge>
                          <Text size="sm" ff="monospace">
                            {member.id}
                          </Text>
                        </Group>
                        <Text size="sm" c="dimmed">
                          Joined{" "}
                          {dayjs(member.created_at).format(
                            "YYYY-MM-DD HH:mm:ss",
                          )}
                        </Text>
                        <Text size="sm" c="dimmed">
                          Updated{" "}
                          {dayjs(member.updated_at).format(
                            "YYYY-MM-DD HH:mm:ss",
                          )}
                        </Text>
                      </Stack>
                      {!isOwner && (
                        <Button
                          color="red"
                          variant="outline"
                          leftSection={<IconTrash size={16} />}
                          onClick={onDelete}
                          loading={isDeleting}
                          disabled={isProcessing}
                        >
                          Remove Member
                        </Button>
                      )}
                    </Group>
                  </>
                )}
              </Stack>
            </Box>
          </form>
        </Box>
      );
    }
  }
}
