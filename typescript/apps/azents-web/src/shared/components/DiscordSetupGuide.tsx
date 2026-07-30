import { Alert, Box, Code, List, Paper, Stack, Text } from "@mantine/core";
import type { ReactElement } from "react";

export interface DiscordSetupGuideCopy {
  title: string;
  description: string;
  createApplication: string;
  enableIntent: string;
  copyIdentifiers: string;
  configureOAuth: string;
  grantBotPermissions: string;
  verifyChannelPermissions: string;
  finishSetup: string;
  gatewayIntentLabel: string;
  oauthScopesLabel: string;
  botPermissionsLabel: string;
  channelPermissionsLabel: string;
  leastPrivilegeNote: string;
}

function GuideCodeBlock({
  label,
  value,
}: {
  label: string;
  value: string;
}): ReactElement {
  return (
    <Stack gap={4} mt="xs" style={{ minWidth: 0 }}>
      <Text size="xs" c="dimmed" fw={700}>
        {label}
      </Text>
      <Box style={{ maxWidth: "100%", minWidth: 0 }}>
        <Code
          block
          style={{
            display: "block",
            maxWidth: "100%",
            minWidth: 0,
            overflowWrap: "anywhere",
            whiteSpace: "pre-wrap",
          }}
        >
          {value}
        </Code>
      </Box>
    </Stack>
  );
}

export function DiscordSetupGuide({
  copy,
}: {
  copy: DiscordSetupGuideCopy;
}): ReactElement {
  return (
    <Paper
      withBorder
      radius="md"
      p="md"
      style={{ maxWidth: "100%", minWidth: 0 }}
    >
      <Stack gap="md" style={{ minWidth: 0 }}>
        <Box>
          <Text fw={700}>{copy.title}</Text>
          <Text size="sm" c="dimmed">
            {copy.description}
          </Text>
        </Box>

        <List type="ordered" size="sm" spacing="sm">
          <List.Item>{copy.createApplication}</List.Item>
          <List.Item>
            {copy.enableIntent}
            <GuideCodeBlock
              label={copy.gatewayIntentLabel}
              value="MESSAGE CONTENT INTENT"
            />
          </List.Item>
          <List.Item>{copy.copyIdentifiers}</List.Item>
          <List.Item>
            {copy.configureOAuth}
            <GuideCodeBlock
              label={copy.oauthScopesLabel}
              value={"bot\napplications.commands"}
            />
          </List.Item>
          <List.Item>
            {copy.grantBotPermissions}
            <GuideCodeBlock
              label={copy.botPermissionsLabel}
              value={
                "View Channels\nSend Messages\nRead Message History\nCreate Public Threads\nSend Messages in Threads\nEmbed Links\nAttach Files"
              }
            />
          </List.Item>
          <List.Item>
            {copy.verifyChannelPermissions}
            <GuideCodeBlock
              label={copy.channelPermissionsLabel}
              value={
                "View Channel\nSend Messages\nRead Message History\nSend Messages in Threads\nEmbed Links\nAttach Files"
              }
            />
          </List.Item>
          <List.Item>{copy.finishSetup}</List.Item>
        </List>

        <Alert color="blue">{copy.leastPrivilegeNote}</Alert>
      </Stack>
    </Paper>
  );
}
