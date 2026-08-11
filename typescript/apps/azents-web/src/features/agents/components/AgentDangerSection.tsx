"use client";

/**
 * Agent deletion (danger) section.
 *
 * Deletes with agent.remove after confirmation modal and moves to /agents list.
 */

import { Alert, Button, Group, Modal, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { trpc } from "@/trpc/client";

interface AgentDangerSectionProps {
  handle: string;
  agentId: string;
}

export function AgentDangerSection({
  handle,
  agentId,
}: AgentDangerSectionProps): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const tDanger = useTranslations("workspace.agents.detail.danger");
  const router = useRouter();
  const utils = trpc.useUtils();
  const [opened, { open, close }] = useDisclosure(false);

  const deleteMutation = trpc.agent.remove.useMutation({
    onSuccess: () => {
      void utils.agent.list.invalidate({ handle });
      router.push(`/w/${handle}/agents`);
    },
  });

  const handleDelete = useCallback(() => {
    deleteMutation.mutate({ handle, agentId });
  }, [deleteMutation, handle, agentId]);

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
