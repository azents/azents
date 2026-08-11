"use client";

import {
  Alert,
  Button,
  Checkbox,
  Code,
  Group,
  Modal,
  Paper,
  rem,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type { RuntimeProfileDeletionState } from "../types";
import type { WorkspaceRuntimeProfileResponse } from "@azents/public-client";

interface RuntimeProfileDeleteModalProps {
  state: RuntimeProfileDeletionState;
  onClose: () => void;
  onConfirm: (profile: WorkspaceRuntimeProfileResponse) => void;
}

export function RuntimeProfileDeleteModal({
  state,
  onClose,
  onConfirm,
}: RuntimeProfileDeleteModalProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeProfiles");
  const profile = state.type === "CLOSED" ? null : state.profile;
  const isSubmitting = state.type === "SUBMITTING";
  const [confirmationName, setConfirmationName] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    setConfirmationName("");
    setAcknowledged(false);
  }, [profile?.id]);

  const isConfirmed =
    profile !== null &&
    confirmationName === profile.display_name &&
    acknowledged;
  const error = state.type === "CONFIRMING" ? state.error : null;

  return (
    <Modal
      centered
      closeOnClickOutside={!isSubmitting}
      closeOnEscape={!isSubmitting}
      opened={profile !== null}
      size="lg"
      title={t("deleteTitle")}
      withCloseButton={!isSubmitting}
      onClose={onClose}
    >
      {profile !== null && (
        <Stack gap="md">
          <Alert
            color="red"
            icon={<IconAlertTriangle size={rem(18)} />}
            title={t("deleteIrreversibleTitle")}
          >
            {t("deleteIrreversibleDescription", {
              name: profile.display_name,
            })}
          </Alert>

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            <Paper withBorder radius="md" p="md">
              <Text fw={700} size="sm">
                {t("deleteSelectionsTitle")}
              </Text>
              <Text c="dimmed" size="sm" mt="xs">
                {t("deleteSelectionsDescription")}
              </Text>
            </Paper>
            <Paper withBorder radius="md" p="md">
              <Text fw={700} size="sm">
                {t("deleteRetainedTitle")}
              </Text>
              <Text c="dimmed" size="sm" mt="xs">
                {t("deleteRetainedDescription")}
              </Text>
            </Paper>
          </SimpleGrid>

          <Text size="sm">
            {t.rich("deleteNameInstruction", {
              name: () => <Code>{profile.display_name}</Code>,
            })}
          </Text>
          <TextInput
            autoComplete="off"
            disabled={isSubmitting}
            label={t("deleteNameLabel")}
            value={confirmationName}
            onChange={(event) => setConfirmationName(event.currentTarget.value)}
          />
          <Checkbox
            checked={acknowledged}
            disabled={isSubmitting}
            label={t("deleteAcknowledgement")}
            onChange={(event) => setAcknowledged(event.currentTarget.checked)}
          />

          {error !== null && (
            <Alert color="red" title={t(`deleteErrors.${error.kind}.title`)}>
              {error.kind === "UNKNOWN"
                ? error.message
                : t(`deleteErrors.${error.kind}.description`)}
            </Alert>
          )}

          <Group justify="flex-end">
            <Button disabled={isSubmitting} variant="default" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              disabled={!isConfirmed}
              loading={isSubmitting}
              onClick={() => onConfirm(profile)}
            >
              {t("deleteConfirm")}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
