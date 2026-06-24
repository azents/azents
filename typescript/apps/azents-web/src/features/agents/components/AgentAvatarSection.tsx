"use client";

/**
 * Agent profile image management section.
 *
 * Current avatar preview + upload button + remove button. Upload uses presigned PUT 3-step
 * flow delegated to `useAgentAvatarContainer`. First implementation uses native file selection +
 * client square validation only — crop UI will be added in separate PR.
 */

import { Alert, Button, Group, Stack, Text, Title } from "@mantine/core";
import { IconTrash, IconUpload } from "@tabler/icons-react";
import { useCallback, useRef } from "react";
import { useAgentAvatarContainer } from "../containers/useAgentAvatarContainer";
import { AgentAvatar } from "./AgentAvatar";
import type { AgentResponse } from "@azents/public-client";

interface AgentAvatarSectionProps {
  handle: string;
  agent: AgentResponse;
}

export function AgentAvatarSection({
  handle,
  agent,
}: AgentAvatarSectionProps): React.ReactElement {
  const { state, uploadFile, removeAvatar, reset } = useAgentAvatarContainer({
    handle,
    agentId: agent.id,
  });
  const inputRef = useRef<HTMLInputElement>(null);

  const handlePickFile = useCallback(() => {
    reset();
    inputRef.current?.click();
  }, [reset]);

  const handleFileChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) {
        return;
      }
      void uploadFile(file);
    },
    [uploadFile],
  );

  const busy =
    state.type === "validating" ||
    state.type === "requesting-url" ||
    state.type === "uploading" ||
    state.type === "finalizing" ||
    state.type === "removing";

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
              loading={busy}
              variant="default"
            >
              {agent.avatar ? "Replace image" : "Upload image"}
            </Button>
            {agent.avatar && (
              <Button
                leftSection={<IconTrash size={14} />}
                onClick={() => void removeAvatar()}
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
        accept="image/jpeg,image/png,image/webp"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />
    </Stack>
  );
}
