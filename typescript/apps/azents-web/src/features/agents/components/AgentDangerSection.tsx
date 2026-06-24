"use client";

/**
 * Agent deletion (danger) section.
 *
 * Deletes with agent.remove after confirmation modal and moves to /agents list.
 */

import { Alert, Button, Group, Modal, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconRefresh, IconTrash } from "@tabler/icons-react";
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
  const [resetOpened, { open: openResetConfirm, close: closeResetConfirm }] =
    useDisclosure(false);

  const deleteMutation = trpc.agent.remove.useMutation({
    onSuccess: () => {
      void utils.agent.list.invalidate({ handle });
      router.push(`/w/${handle}/agents`);
    },
  });

  const handleDelete = useCallback(() => {
    deleteMutation.mutate({ handle, agentId });
  }, [deleteMutation, handle, agentId]);

  const resetMutation = trpc.chat.resetAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      closeResetConfirm();
      await utils.chat.getAgentWorkspace.invalidate({
        agentId: variables.agentId,
      });
      await utils.chat.readAgentWorkspacePath.invalidate();
    },
  });

  const handleReset = useCallback(() => {
    resetMutation.mutate({ handle, agentId });
  }, [agentId, handle, resetMutation]);

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
              leftSection={<IconRefresh size={14} />}
              onClick={openResetConfirm}
              variant="light"
            >
              {tDanger("resetRuntime")}
            </Button>
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

      <Modal
        opened={resetOpened}
        onClose={closeResetConfirm}
        title={tDanger("resetRuntime")}
        centered
      >
        <Stack gap="md">
          <Text>{tDanger("resetRuntimeConfirm")}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={closeResetConfirm}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              onClick={handleReset}
              loading={resetMutation.isPending}
            >
              {tDanger("resetRuntime")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
