"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { getRuntimeExecutionPolicyIssue } from "../runtimeExecutionPresentation";
import { RuntimeExecutionPolicyEditor } from "./RuntimeExecutionPolicyEditor";
import type {
  RuntimeExecutionPageContentProps,
  RuntimeExecutionProfileDraft,
} from "../types";
import type { RuntimeExecutionManagementCapabilitiesResponse } from "@azents/admin-client";

function ProfileEditor({
  draft,
  creating,
  saving,
  retiring,
  capabilities,
  onChange,
  onSave,
  onRetire,
}: {
  draft: RuntimeExecutionProfileDraft;
  creating: boolean;
  saving: boolean;
  retiring: boolean;
  capabilities: RuntimeExecutionManagementCapabilitiesResponse;
  onChange: (draft: RuntimeExecutionProfileDraft) => void;
  onSave: () => void;
  onRetire: () => void;
}): React.ReactElement {
  const policyIssue = getRuntimeExecutionPolicyIssue(
    draft.policy,
    capabilities,
  );
  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={3}>
            {creating ? "Create Profile" : draft.displayName}
          </Title>
          {!creating && (
            <Text size="sm" c="dimmed">
              Version {draft.expectedVersion} · <Code>{draft.id}</Code>
            </Text>
          )}
        </Stack>
        <Group>
          {!creating && !draft.reserved && (
            <Button
              color="red"
              variant="light"
              loading={retiring}
              onClick={onRetire}
            >
              Retire
            </Button>
          )}
          <Button
            loading={saving}
            disabled={
              draft.id.trim().length === 0 ||
              draft.displayName.trim().length === 0 ||
              policyIssue !== null
            }
            onClick={onSave}
          >
            {creating ? "Create Profile" : "Save Profile"}
          </Button>
        </Group>
      </Group>
      {draft.reserved && (
        <Alert color="blue">
          Reserved system Profiles define stable identities and cannot be
          retired. Their policy remains editable.
        </Alert>
      )}
      {policyIssue !== null && <Alert color="yellow">{policyIssue}</Alert>}
      {creating && (
        <TextInput
          label="Profile ID"
          description="Lowercase letters, numbers, and hyphens."
          value={draft.id}
          onChange={(event) =>
            onChange({ ...draft, id: event.currentTarget.value })
          }
        />
      )}
      <TextInput
        label="Display name"
        value={draft.displayName}
        onChange={(event) =>
          onChange({ ...draft, displayName: event.currentTarget.value })
        }
      />
      <Textarea
        label="Description"
        value={draft.description}
        autosize
        minRows={2}
        onChange={(event) =>
          onChange({ ...draft, description: event.currentTarget.value })
        }
      />
      <RuntimeExecutionPolicyEditor
        key={creating ? "new-profile" : draft.id}
        policy={draft.policy}
        capabilities={capabilities}
        onChange={(policy) => onChange({ ...draft, policy })}
      />
    </Stack>
  );
}

export function RuntimeExecutionPageContent({
  state,
  profileDraft,
  selectedProfileId,
  profileDetailOpen,
  profileModalOpened,
  savingProfile,
  retiringProfile,
  actionError,
  onSelectProfile,
  onProfileDetailClose,
  onProfileDraftChange,
  onOpenCreateProfile,
  onCloseProfileModal,
  onSaveProfile,
  onRetireProfile,
}: RuntimeExecutionPageContentProps): React.ReactElement {
  const capabilities = state.type === "LOADED" ? state.capabilities : null;
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Modal
        opened={profileModalOpened}
        onClose={onCloseProfileModal}
        title="Create Runtime Execution Profile"
        size="xl"
      >
        {profileDraft && capabilities && (
          <ProfileEditor
            draft={profileDraft}
            creating
            saving={savingProfile}
            retiring={false}
            capabilities={capabilities}
            onChange={onProfileDraftChange}
            onSave={onSaveProfile}
            onRetire={onRetireProfile}
          />
        )}
      </Modal>

      <Stack gap={4} p="md">
        <Title order={2}>Runtime Execution</Title>
        <Text c="dimmed">
          Manage reusable policy ceilings and safe policy audit history.
        </Text>
      </Stack>
      <Stack gap="sm" px="md">
        {actionError && (
          <Alert color="red" title="Action failed">
            {actionError}
          </Alert>
        )}
        {state.type === "LOADING" && <Loader />}
        {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
      </Stack>
      {state.type === "LOADED" && (
        <Tabs
          defaultValue="profiles"
          px="md"
          pb="md"
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <Tabs.List>
            <Tabs.Tab value="profiles">
              Profiles ({state.profiles.length})
            </Tabs.Tab>
            <Tabs.Tab value="audit">
              Audit ({state.auditEvents.length})
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel
            value="profiles"
            pt="lg"
            style={{ flex: 1, minHeight: 0 }}
          >
            <MasterDetailLayout
              columns="1fr 2fr"
              master={
                <ScrollArea h="100%" p="sm" type="auto">
                  <Stack gap="xs">
                    <Button variant="light" onClick={onOpenCreateProfile}>
                      Create Profile
                    </Button>
                    {state.profiles.map((profile) => (
                      <Paper
                        key={profile.id}
                        withBorder
                        p="sm"
                        radius="sm"
                        bg={
                          profile.id === selectedProfileId
                            ? "var(--mantine-color-blue-light)"
                            : "transparent"
                        }
                        style={{ cursor: "pointer" }}
                        onClick={() => onSelectProfile(profile.id)}
                      >
                        <Stack gap={3}>
                          <Group justify="space-between" wrap="nowrap">
                            <Text fw={600} truncate>
                              {profile.display_name}
                            </Text>
                            <Badge
                              color={
                                profile.lifecycle === "active"
                                  ? "green"
                                  : "gray"
                              }
                              variant="light"
                            >
                              {profile.lifecycle}
                            </Badge>
                          </Group>
                          <Text size="xs" c="dimmed">
                            v{profile.version} · {profile.id}
                          </Text>
                        </Stack>
                      </Paper>
                    ))}
                  </Stack>
                </ScrollArea>
              }
              detail={
                <Stack p={{ base: "md", sm: "xl" }}>
                  {profileDraft ? (
                    <ProfileEditor
                      draft={profileDraft}
                      creating={false}
                      saving={savingProfile}
                      retiring={retiringProfile}
                      capabilities={state.capabilities}
                      onChange={onProfileDraftChange}
                      onSave={onSaveProfile}
                      onRetire={onRetireProfile}
                    />
                  ) : (
                    <Alert color="yellow">No Profiles are available.</Alert>
                  )}
                </Stack>
              }
              detailOpen={profileDetailOpen}
              onDetailClose={onProfileDetailClose}
            />
          </Tabs.Panel>

          <Tabs.Panel
            value="audit"
            pt="lg"
            style={{ flex: 1, minHeight: 0, overflow: "auto" }}
          >
            <Stack gap="sm">
              {state.auditEvents.length === 0 && (
                <Alert color="yellow">No Runtime Execution audit events.</Alert>
              )}
              {state.auditEvents.map((event) => (
                <Paper key={event.id} withBorder p="md" radius="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={3}>
                      <Group gap="xs">
                        <Badge variant="light">{event.management_layer}</Badge>
                        <Badge variant="outline">{event.classification}</Badge>
                        <Text fw={600}>{event.event_type}</Text>
                      </Group>
                      <Text size="sm" c="dimmed">
                        {event.reason_code} → {event.outcome_code}
                      </Text>
                      <Text size="xs" ff="monospace">
                        {event.changed_paths.join(", ") || "Metadata only"}
                      </Text>
                    </Stack>
                    <Text size="xs" c="dimmed">
                      {new Date(event.created_at).toLocaleString()}
                    </Text>
                  </Group>
                </Paper>
              ))}
            </Stack>
          </Tabs.Panel>
        </Tabs>
      )}
    </Box>
  );
}
