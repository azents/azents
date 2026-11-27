import {
  Alert,
  Badge,
  Button,
  Group,
  Modal,
  Paper,
  PasswordInput,
  Stack,
  Text,
} from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { VaultRequestView as RequestData } from "@azents/public-client";
import type { FormEvent, ReactElement } from "react";

export function VaultRequestCard({
  request,
  loading,
  onOpen,
}: {
  request: RequestData | null;
  loading: boolean;
  onOpen: () => void;
}): ReactElement {
  const t = useTranslations("chat.vaultRequest");
  return (
    <Paper
      withBorder
      p="md"
      radius="md"
      maw="100%"
      component="section"
      aria-label={t("title")}
    >
      <Stack gap="xs">
        <Group gap="xs" justify="space-between">
          <Group gap="xs">
            <IconLock aria-hidden="true" size="1rem" />
            <Text size="sm" fw={600}>
              {t("title")}
            </Text>
          </Group>
          <Badge
            variant="light"
            color={request?.status === "submitted" ? "green" : "gray"}
          >
            {t(request?.status ?? (loading ? "loading" : "unavailable"))}
          </Badge>
        </Group>
        {request !== null && (
          <>
            <Text size="sm" style={{ overflowWrap: "anywhere" }}>
              {request.purpose}
            </Text>
            <Text size="xs" c="dimmed" style={{ overflowWrap: "anywhere" }}>
              {request.fields.map((field) => field.label).join(" · ")}
            </Text>
            {request.can_submit && (
              <Group>
                <Button variant="light" size="compact-sm" onClick={onOpen}>
                  {t("openForm")}
                </Button>
              </Group>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );
}

export function VaultRequestDialog({
  agentName,
  request,
  loading,
  values,
  busy,
  failed,
  onClose,
  onFieldChange,
  onSubmit,
}: {
  agentName: string;
  request: RequestData | null;
  loading: boolean;
  values: ReadonlyMap<string, string>;
  busy: boolean;
  failed: boolean;
  onClose: () => void;
  onFieldChange: (name: string, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}): ReactElement {
  const t = useTranslations("chat.vaultRequest");
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("title")}
      closeButtonProps={{ "aria-label": t("close") }}
    >
      <Stack gap="sm">
        <Text size="sm" fw={600}>
          {agentName}
        </Text>
        {request === null ? (
          <Text size="sm">{t(loading ? "loading" : "unavailable")}</Text>
        ) : !request.can_submit ? (
          <Text size="sm">
            {t(request.status === "open" ? "unavailable" : request.status)}
          </Text>
        ) : (
          <form onSubmit={onSubmit} autoComplete="off">
            <Stack gap="sm">
              <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                {request.purpose}
              </Text>
              {request.fields.map((field) => (
                <PasswordInput
                  key={field.name}
                  label={field.label}
                  autoComplete="new-password"
                  value={values.get(field.name) ?? ""}
                  onChange={(event) =>
                    onFieldChange(field.name, event.currentTarget.value)
                  }
                  disabled={busy}
                  maxLength={32768}
                  required
                />
              ))}
              {failed && (
                <Alert color="red" role="alert">
                  {t("submitFailed")}
                </Alert>
              )}
              <Group justify="flex-end">
                <Button variant="default" onClick={onClose}>
                  {t("close")}
                </Button>
                <Button type="submit" loading={busy}>
                  {t("submit")}
                </Button>
              </Group>
            </Stack>
          </form>
        )}
      </Stack>
    </Modal>
  );
}
