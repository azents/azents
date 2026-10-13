"use client";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  CopyButton,
  Group,
  Loader,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import type { GoogleApplicationCardProps } from "../containers/useGoogleApplicationCardContainer";

export function GoogleApplicationCard({
  state,
}: GoogleApplicationCardProps): React.ReactElement {
  if (state.type === "LOADING") {
    return (
      <Paper withBorder p="lg">
        <Loader size="sm" aria-label="Loading Google application settings" />
      </Paper>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="red" title="Unable to load Google application settings">
        <Button variant="subtle" onClick={state.onReload}>
          Reload
        </Button>
      </Alert>
    );
  }
  const { detail, draft } = state;
  const clientOwned = detail.client_id_source === "environment";
  const secretOwned = detail.client_secret_source === "environment";
  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={4}>Google service authorization</Title>
          <Badge
            color={
              detail.status === "configured_unverified" ? "blue" : "yellow"
            }
          >
            {detail.status === "configured_unverified"
              ? "Configured locally"
              : detail.status === "incomplete"
                ? "Incomplete"
                : "Not configured"}
          </Badge>
        </Group>
        <Text size="sm">
          Configure the operator-owned OAuth application used by Google Toolkits
          for Calendar, Drive and Gmail. The configured application is not proof
          of Preview eligibility or live service access.
        </Text>
        <Alert color="yellow">
          Changing the client ID makes grants issued for the previous client
          ineligible and requires explicit reconnection. Rotating the secret for
          the same client does not replace the connected Google account.
          Existing credentials are not copied into new authorization candidates.
        </Alert>
        {state.reloadRequired && (
          <Alert
            color="yellow"
            title={
              state.error === "uncertain"
                ? "Save result is uncertain"
                : "Current settings changed"
            }
          >
            Reload the current settings before retrying. Reload discards this
            draft, including an unsaved secret.
          </Alert>
        )}
        <TextInput
          label="Client ID"
          description={
            clientOwned
              ? "Owned by process environment; read-only here."
              : "A blank edited value clears the Admin client ID."
          }
          value={draft.clientId}
          disabled={clientOwned || state.saving || state.reloadRequired}
          onChange={(event) =>
            state.onDraftChange({
              clientId: event.currentTarget.value,
              clientTouched: true,
            })
          }
        />
        <Group gap="xs">
          <Badge variant="light">Client ID: {detail.client_id_source}</Badge>
          <Badge variant="light">Secret: {detail.client_secret_source}</Badge>
          <Text size="xs">
            {detail.client_secret_configured
              ? "Secret configured"
              : "No secret configured"}
          </Text>
        </Group>
        <PasswordInput
          label="Client secret replacement"
          description={
            secretOwned
              ? "Owned by process environment; read-only here."
              : "Existing secret plaintext is never returned. Leave empty to keep it."
          }
          value={draft.secret}
          disabled={
            secretOwned ||
            draft.clearSecret ||
            state.saving ||
            state.reloadRequired
          }
          onChange={(event) =>
            state.onDraftChange({
              secret: event.currentTarget.value,
              clearSecret: false,
            })
          }
        />
        <Checkbox
          label="Clear stored client secret"
          checked={draft.clearSecret}
          disabled={secretOwned || state.saving || state.reloadRequired}
          onChange={(event) =>
            state.onDraftChange({
              clearSecret: event.currentTarget.checked,
              secret: "",
            })
          }
        />
        <Text size="sm" fw={600}>
          Registered callback URL
        </Text>
        {detail.callback_url == null ? (
          <Text size="sm" c="dimmed">
            Unavailable until the public Web URL is configured.
          </Text>
        ) : (
          <Group wrap="wrap">
            <Code style={{ overflowWrap: "anywhere" }}>
              {detail.callback_url}
            </Code>
            <CopyButton value={detail.callback_url}>
              {({ copied, copy }) => (
                <Button variant="subtle" size="compact-sm" onClick={copy}>
                  {copied ? "Copied" : "Copy"}
                </Button>
              )}
            </CopyButton>
          </Group>
        )}
        <Text size="xs" c="dimmed">
          Register this exact URL with Google. Application permissions and
          Preview access must be verified separately. No live authorization is
          performed by this screen.
        </Text>
        <Group justify="space-between">
          <Text size="xs" c="dimmed">
            Admin version {detail.admin_version}
            {state.dirty ? " · Unsaved changes" : ""}
          </Text>
          <Group>
            <Button
              variant="default"
              disabled={state.saving}
              onClick={state.onReload}
            >
              Reload and discard draft
            </Button>
            <Button
              loading={state.saving}
              disabled={!state.dirty || state.reloadRequired}
              onClick={state.onSave}
            >
              Save application settings
            </Button>
          </Group>
        </Group>
      </Stack>
    </Paper>
  );
}
