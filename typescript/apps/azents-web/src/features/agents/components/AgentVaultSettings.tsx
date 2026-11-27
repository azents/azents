"use client";

import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import type { AgentVaultEntryMetadata } from "@azents/public-client";

export type VaultEditor =
  { type: "create" } | { type: "replace" | "delete"; name: string };

export interface AgentVaultSettingsProps {
  state:
    | { type: "loading" | "error" }
    | { type: "ready"; entries: AgentVaultEntryMetadata[] };
  editor: VaultEditor | null;
  pending: boolean;
  error: boolean;
  onEditor: (editor: VaultEditor | null) => void;
  onSubmit: (name: string, value: string) => Promise<void>;
}

type CopyKey =
  | "title"
  | "description"
  | "add"
  | "replace"
  | "remove"
  | "empty"
  | "unavailable"
  | "failed"
  | "name"
  | "value"
  | "save"
  | "cancel"
  | "confirmRemove";

export function AgentVaultSettings({
  state,
  editor,
  pending,
  error,
  onEditor,
  onSubmit,
  t,
}: AgentVaultSettingsProps & {
  t: (key: CopyKey) => string;
}): React.ReactElement {
  return (
    <Stack gap="md" p="md">
      <Group justify="space-between">
        <Title order={2}>{t("title")}</Title>
        {state.type === "ready" && (
          <Button onClick={() => onEditor({ type: "create" })}>
            {t("add")}
          </Button>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        {t("description")}
      </Text>
      {state.type === "loading" && <Loader aria-label={t("title")} />}
      {state.type === "error" && <Alert color="red">{t("unavailable")}</Alert>}
      {state.type === "ready" && (
        <Stack gap="xs">
          {state.entries.length === 0 && <Text c="dimmed">{t("empty")}</Text>}
          {state.entries.map((entry) => (
            <Paper key={entry.name} withBorder p="sm">
              <Group justify="space-between">
                <Stack gap={0} maw="100%">
                  <Text fw={600} style={{ overflowWrap: "anywhere" }}>
                    {entry.name}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {entry.contributor_label}
                  </Text>
                </Stack>
                <Group>
                  <Button
                    variant="subtle"
                    onClick={() =>
                      onEditor({ type: "replace", name: entry.name })
                    }
                  >
                    {t("replace")}
                  </Button>
                  <Button
                    variant="subtle"
                    color="red"
                    onClick={() =>
                      onEditor({ type: "delete", name: entry.name })
                    }
                  >
                    {t("remove")}
                  </Button>
                </Group>
              </Group>
            </Paper>
          ))}
        </Stack>
      )}
      <Modal
        opened={editor !== null && state.type === "ready"}
        onClose={() => onEditor(null)}
        closeOnClickOutside={!pending}
        closeOnEscape={!pending}
        title={
          editor?.type === "delete"
            ? t("remove")
            : editor?.type === "replace"
              ? t("replace")
              : t("add")
        }
      >
        {editor !== null && state.type === "ready" && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const input = new FormData(form);
              const name = input.get("name");
              const value = input.get("value");
              form.reset();
              void onSubmit(
                typeof name === "string" ? name : "",
                typeof value === "string" ? value : "",
              );
            }}
          >
            <Stack>
              {editor.type === "create" ? (
                <TextInput
                  name="name"
                  label={t("name")}
                  required
                  maxLength={255}
                  disabled={pending}
                />
              ) : (
                <Text fw={600}>{editor.name}</Text>
              )}
              {editor.type === "delete" ? (
                <Text size="sm">{t("confirmRemove")}</Text>
              ) : (
                <PasswordInput
                  name="value"
                  label={t("value")}
                  autoComplete="new-password"
                  maxLength={32768}
                  disabled={pending}
                />
              )}
              {error && <Alert color="red">{t("failed")}</Alert>}
              <Group justify="flex-end">
                <Button
                  variant="default"
                  disabled={pending}
                  onClick={() => onEditor(null)}
                >
                  {t("cancel")}
                </Button>
                <Button
                  type="submit"
                  {...(editor.type === "delete" ? { color: "red" } : {})}
                  loading={pending}
                >
                  {editor.type === "delete" ? t("remove") : t("save")}
                </Button>
              </Group>
            </Stack>
          </form>
        )}
      </Modal>
    </Stack>
  );
}
