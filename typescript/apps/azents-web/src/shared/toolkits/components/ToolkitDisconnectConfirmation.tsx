"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";

/** Common confirmation body; Provider-specific revocation limits remain explicit. */
export function ToolkitDisconnectConfirmation({
  personal,
  description,
  detail,
  confirmLabel,
  cancelLabel,
  pending,
  onConfirm,
  onCancel,
}: {
  personal: boolean;
  description: string;
  detail?: string;
  confirmLabel: string;
  cancelLabel: string;
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}): React.ReactElement {
  const t = useTranslations("account.personalTools");
  return (
    <Stack>
      <Text size="sm">
        {personal ? t("disconnectExplanation") : description}
      </Text>
      {detail && (
        <Text size="sm" c="dimmed">
          {detail}
        </Text>
      )}
      <Group justify="flex-end">
        <Button
          type="button"
          variant="default"
          disabled={pending}
          onClick={onCancel}
          data-autofocus
        >
          {cancelLabel}
        </Button>
        <Button type="button" color="red" loading={pending} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </Group>
    </Stack>
  );
}
