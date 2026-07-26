"use client";

import {
  Alert,
  Badge,
  Button,
  Code,
  Divider,
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
import { isRuntimeExecutionPolicySupported } from "../runtimeExecutionPresentation";
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
  const readOnly = draft.reserved;
  const policySupported = isRuntimeExecutionPolicySupported(
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
          {!creating && !readOnly && (
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
              readOnly ||
              draft.id.trim().length === 0 ||
              draft.displayName.trim().length === 0 ||
              !policySupported
            }
            onClick={onSave}
          >
            {creating ? "Create Profile" : "Save Profile"}
          </Button>
        </Group>
      </Group>
      {readOnly && (
        <Alert color="blue">
          Reserved system Profiles are read-only and cannot be retired.
        </Alert>
      )}
      {!readOnly && !policySupported && (
        <Alert color="yellow">
          This draft requests Runtime authority that the current server
          capability gate cannot enforce. Remove the unavailable authority
          before saving.
        </Alert>
      )}
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
        disabled={readOnly}
        onChange={(event) =>
          onChange({ ...draft, displayName: event.currentTarget.value })
        }
      />
      <Textarea
        label="Description"
        value={draft.description}
        disabled={readOnly}
        autosize
        minRows={2}
        onChange={(event) =>
          onChange({ ...draft, description: event.currentTarget.value })
        }
      />
      <RuntimeExecutionPolicyEditor
        policy={draft.policy}
        capabilities={capabilities}
        readOnly={readOnly}
        onChange={(policy) => onChange({ ...draft, policy })}
      />
    </Stack>
  );
}

export function RuntimeExecutionPageContent({
  state,
  platformDraft,
  profileDraft,
  selectedProfileId,
  profileModalOpened,
  savingPlatform,
  savingProfile,
  retiringProfile,
  actionError,
  onPlatformDraftChange,
  onSavePlatform,
  onSelectProfile,
  onProfileDraftChange,
  onOpenCreateProfile,
  onCloseProfileModal,
  onSaveProfile,
  onRetireProfile,
}: RuntimeExecutionPageContentProps): React.ReactElement {
  const capabilities =
    state.type === "LOADED" ? state.platform.capabilities : null;
  return (
    <Stack gap="lg" p="md">
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

      <Stack gap={4}>
        <Title order={2}>Runtime Execution</Title>
        <Text c="dimmed">
          Manage installation limits, reusable Profiles, and safe policy audit
          history.
        </Text>
      </Stack>
      {actionError && (
        <Alert color="red" title="Action failed">
          {actionError}
        </Alert>
      )}
      {state.type === "LOADING" && <Loader />}
      {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
      {state.type === "LOADED" && (
        <Tabs defaultValue="platform">
          <Tabs.List>
            <Tabs.Tab value="platform">Platform limits</Tabs.Tab>
            <Tabs.Tab value="profiles">
              Profiles ({state.profiles.length})
            </Tabs.Tab>
            <Tabs.Tab value="audit">
              Audit ({state.auditEvents.length})
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="platform" pt="lg">
            <Stack gap="md">
              <Group justify="space-between" align="flex-start">
                <Stack gap={2}>
                  <Text fw={600}>Installation-wide policy ceiling</Text>
                  <Text size="sm" c="dimmed">
                    Version {state.platform.version} · Digest{" "}
                    <Code>{state.platform.digest.slice(0, 16)}</Code>
                  </Text>
                </Stack>
                <Button
                  loading={savingPlatform}
                  disabled={
                    platformDraft === null ||
                    !isRuntimeExecutionPolicySupported(
                      platformDraft,
                      state.platform.capabilities,
                    )
                  }
                  onClick={onSavePlatform}
                >
                  Save Platform policy
                </Button>
              </Group>
              {platformDraft && (
                <RuntimeExecutionPolicyEditor
                  policy={platformDraft}
                  capabilities={state.platform.capabilities}
                  onChange={onPlatformDraftChange}
                />
              )}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="profiles" pt="lg">
            <Group align="stretch" gap={0} wrap="nowrap">
              <ScrollArea w={{ base: 240, sm: 320 }} type="auto">
                <Stack gap="xs" pr="md">
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
                              profile.lifecycle === "active" ? "green" : "gray"
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
              <Divider orientation="vertical" />
              <Stack pl="xl" style={{ flex: 1, minWidth: 0 }}>
                {profileDraft ? (
                  <ProfileEditor
                    draft={profileDraft}
                    creating={false}
                    saving={savingProfile}
                    retiring={retiringProfile}
                    capabilities={state.platform.capabilities}
                    onChange={onProfileDraftChange}
                    onSave={onSaveProfile}
                    onRetire={onRetireProfile}
                  />
                ) : (
                  <Alert color="yellow">No Profiles are available.</Alert>
                )}
              </Stack>
            </Group>
          </Tabs.Panel>

          <Tabs.Panel value="audit" pt="lg">
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
    </Stack>
  );
}
