"use client";
import { Alert, Button, Group, Stack, Text, Title } from "@mantine/core";
import { IconTrash, IconUpload } from "@tabler/icons-react";
/**
 * Agent profile image management section.
 *
 * Current avatar preview + upload button + remove button. Upload uses presigned PUT 3-step
 * flow delegated to `useAgentAvatarContainer`. First implementation uses native file selection +
 * client square validation only — crop UI will be added in separate PR.
 */
import { AgentAvatar } from "@/shared/agent-session/AgentAvatar";
import { useAgentAvatarSectionController } from "../containers/useAgentAvatarSectionController";
import type { AgentAvatarSectionViewProps } from "../containers/useAgentAvatarSectionController";
import type { AgentResponse } from "@azents/public-client";

interface AgentAvatarSectionProps {
  handle: string;
  agent: AgentResponse;
}

export function AgentAvatarSection(
  props: AgentAvatarSectionProps,
): React.ReactElement {
  return <AgentAvatarSectionView {...useAgentAvatarSectionController(props)} />;
}

export function AgentAvatarSectionView({
  agent,
  state,
  removeAvatar,
  inputRef,
  handlePickFile,
  handleFileChange,
  busy,
}: AgentAvatarSectionViewProps): React.ReactElement {
  return (
    <Stack gap="md">
      <Title order={5}>Profile image</Title>
      <Group align="center" gap="lg">
        <AgentAvatar
          name={agent.name}
          avatar={agent.avatar ?? null}
          size={96}
          radius="xl"
        />
        <Stack gap="xs">
          <Text size="xs" c="dimmed">
            Square JPEG / PNG / WebP up to 5 MB. Thumbnails are generated
            automatically.
          </Text>
          <Group gap="sm">
            <Button
              leftSection={<IconUpload size={14} />}
              onClick={handlePickFile}
              disabled={agent.deletion_status !== null}
              loading={busy}
              variant="default"
            >
              {agent.avatar ? "Replace image" : "Upload image"}
            </Button>
            {agent.avatar && (
              <Button
                leftSection={<IconTrash size={14} />}
                onClick={() => void removeAvatar()}
                disabled={agent.deletion_status !== null}
                loading={state.type === "removing"}
                color="red"
                variant="subtle"
              >
                Remove
              </Button>
            )}
          </Group>
        </Stack>
      </Group>
      {state.type === "error" && (
        <Alert color="red" variant="light">
          {state.message}
        </Alert>
      )}
      <input
        ref={inputRef}
        type="file"
        disabled={agent.deletion_status !== null}
        accept="image/jpeg,image/png,image/webp"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />
    </Stack>
  );
}
