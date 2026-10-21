"use client";
import { Alert, Button, Group, Modal, Stack, Text, Title } from "@mantine/core";
/**
 * Agent deletion (danger) section.
 *
 * Deletes with agent.remove after confirmation modal and moves to /agents list.
 */
import { IconTrash } from "@tabler/icons-react";
import { useAgentDangerSectionController } from "../containers/useAgentDangerSectionController";
import type { AgentDangerSectionViewProps } from "../containers/useAgentDangerSectionController";

interface AgentDangerSectionProps {
  readOnly: boolean;
  handle: string;
  agentId: string;
}

export function AgentDangerSection(
  props: AgentDangerSectionProps,
): React.ReactElement {
  return <AgentDangerSectionView {...useAgentDangerSectionController(props)} />;
}

export function AgentDangerSectionView({
  readOnly,
  t,
  tDanger,
  opened,
  open,
  close,
  deleteMutation,
  handleDelete,
}: AgentDangerSectionViewProps): React.ReactElement {
  return (
    <Stack gap="md">
      <Title order={4} c="red">
        {tDanger("title")}
      </Title>
      <Alert color="red" variant="light">
        <Stack gap="sm">
          <Text size="sm">{tDanger("deleteWarning")}</Text>
          <Group>
            <Button
              color="red"
              leftSection={<IconTrash size={14} />}
              onClick={open}
              disabled={readOnly}
              variant="filled"
            >
              {t("delete")}
            </Button>
          </Group>
        </Stack>
      </Alert>

      <Modal opened={opened} onClose={close} title={t("delete")} centered>
        <Stack gap="md">
          <Text>{t("deleteConfirm")}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              onClick={handleDelete}
              disabled={readOnly}
              loading={deleteMutation.isPending}
            >
              {t("delete")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
