"use client";

import {
  Alert,
  Anchor,
  Badge,
  Code,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useConfig } from "@/config/client";
import { getPublicRoutePath } from "@/shared/lib/auth-policy";
import type { WorkspaceRuntimeProfileAdminComponentProps } from "../containers/useWorkspaceRuntimeProfileAdminContainer";

function DetailField({
  label,
  value,
  monospace = false,
}: {
  label: string;
  value: string;
  monospace?: boolean;
}): React.ReactElement {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text
        size="sm"
        ff={monospace ? "monospace" : "var(--mantine-font-family)"}
        style={{ overflowWrap: "anywhere" }}
      >
        {value}
      </Text>
    </Stack>
  );
}

export function WorkspaceRuntimeProfileAdminView({
  state,
}: WorkspaceRuntimeProfileAdminComponentProps): React.ReactElement {
  const { publicBaseUrl } = useConfig();
  const workspacesPath = getPublicRoutePath(publicBaseUrl, "/workspaces");

  switch (state.type) {
    case "LOADING":
      return (
        <Group justify="center" py="xl">
          <Loader />
          <Text>Loading Workspace Runtime Profile…</Text>
        </Group>
      );
    case "NOT_FOUND":
      return (
        <Stack gap="md">
          <Anchor href={workspacesPath}>← Back to Workspaces</Anchor>
          <Alert color="yellow" title="Workspace Runtime Profile not found">
            The Workspace or Runtime Profile is no longer available in the
            current Admin inventory.
          </Alert>
        </Stack>
      );
    case "ERROR":
      return (
        <Stack gap="md">
          <Anchor href={workspacesPath}>← Back to Workspaces</Anchor>
          <Alert color="red" title="Could not load Runtime Profile">
            {state.message}
          </Alert>
        </Stack>
      );
    case "LOADED": {
      const { detail } = state;
      return (
        <Stack gap="lg">
          <Stack gap="xs">
            <Anchor href={workspacesPath}>← Back to Workspaces</Anchor>
            <Group justify="space-between" align="flex-start">
              <Stack gap={2}>
                <Title order={2}>{detail.display_name}</Title>
                <Text c="dimmed">
                  {detail.workspace_name} · @{detail.workspace_handle}
                </Text>
              </Stack>
              <Badge
                color={detail.lifecycle === "active" ? "green" : "gray"}
                variant="light"
              >
                {detail.lifecycle}
              </Badge>
            </Group>
            <Text size="sm">
              {detail.description || "No description provided."}
            </Text>
          </Stack>

          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            <Paper withBorder p="md">
              <Stack gap="md">
                <Text fw={600}>Workspace Profile</Text>
                <DetailField
                  label="Workspace ID"
                  value={detail.workspace_id}
                  monospace
                />
                <DetailField
                  label="Profile ID"
                  value={detail.profile_id}
                  monospace
                />
                <DetailField label="Version" value={String(detail.version)} />
                <DetailField label="Digest" value={detail.digest} monospace />
                <Group gap="xs">
                  <Badge variant="outline">
                    {detail.selected_agent_count} selected{" "}
                    {detail.selected_agent_count === 1 ? "Agent" : "Agents"}
                  </Badge>
                  <Badge variant="outline">
                    {detail.running_runtime_count} running{" "}
                    {detail.running_runtime_count === 1
                      ? "Runtime"
                      : "Runtimes"}
                  </Badge>
                </Group>
              </Stack>
            </Paper>

            <Paper withBorder p="md">
              <Stack gap="md">
                <Text fw={600}>Selected infrastructure</Text>
                <DetailField
                  label="Provider"
                  value={`${detail.provider_display_name} (${detail.provider_id})`}
                />
                <DetailField
                  label="Provider kind"
                  value={detail.provider_kind}
                />
                <DetailField
                  label="Infrastructure Profile"
                  value={detail.infrastructure_profile_display_name}
                />
                <DetailField
                  label="Infrastructure Profile ID"
                  value={detail.infrastructure_profile_id}
                  monospace
                />
                <Group gap="xs">
                  <Badge variant="outline">
                    {detail.infrastructure_profile_kind}
                  </Badge>
                  <Badge
                    color={
                      detail.infrastructure_profile_lifecycle === "active"
                        ? "green"
                        : "gray"
                    }
                    variant="light"
                  >
                    {detail.infrastructure_profile_lifecycle}
                  </Badge>
                  <Badge variant="outline">
                    Version {detail.infrastructure_profile_version}
                  </Badge>
                </Group>
              </Stack>
            </Paper>
          </SimpleGrid>

          <Paper withBorder p="md">
            <Stack gap="sm">
              <Text fw={600}>Runtime policy</Text>
              <Code block style={{ overflowX: "auto" }}>
                {JSON.stringify(detail.policy, null, 2)}
              </Code>
            </Stack>
          </Paper>

          <Paper withBorder p="md">
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <DetailField
                label="Created"
                value={dayjs(detail.created_at).format("YYYY-MM-DD HH:mm:ss Z")}
              />
              <DetailField
                label="Updated"
                value={dayjs(detail.updated_at).format("YYYY-MM-DD HH:mm:ss Z")}
              />
            </SimpleGrid>
          </Paper>
        </Stack>
      );
    }
  }
}
