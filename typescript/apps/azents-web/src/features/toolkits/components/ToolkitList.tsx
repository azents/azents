"use client";

/**
 * Toolkit list UI component.
 *
 * Displays Toolkit card list and provides delete/enabled toggle.
 */

import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Container,
  Group,
  Loader,
  Modal,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconAlertTriangle,
  IconEdit,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useState } from "react";
import type { ToolkitListContainerOutput } from "../containers/useToolkitListContainer";
import type { ToolkitConfigResponse } from "@azents/public-client";

export function ToolkitList(
  props: ToolkitListContainerOutput,
): React.ReactElement {
  const { handle, listState, onDelete, onToggleEnabled } = props;
  const t = useTranslations("workspace.toolkits");

  const [deleteOpened, { open: openDelete, close: closeDelete }] =
    useDisclosure(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const handleDeleteClick = useCallback(
    (toolkitId: string): void => {
      setDeleteTarget(toolkitId);
      openDelete();
    },
    [openDelete],
  );

  const handleDeleteConfirm = useCallback((): void => {
    if (deleteTarget) {
      onDelete(deleteTarget);
      setDeleteTarget(null);
      closeDelete();
    }
  }, [deleteTarget, onDelete, closeDelete]);

  const basePath = `/w/${handle}/toolkits`;

  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={3}>{t("headline")}</Title>
          <Button
            component={Link}
            href={`${basePath}/new`}
            leftSection={<IconPlus size={16} />}
          >
            {t("addToolkit")}
          </Button>
        </Group>

        <Text c="dimmed" size="sm">
          {t("description")}
        </Text>

        {listState.type === "LOADING" && <Loader />}
        {listState.type === "ERROR" && (
          <Alert color="red">{t("loadError")}</Alert>
        )}
        {listState.type === "READY" && listState.configs.length === 0 && (
          <Text c="dimmed">{t("empty")}</Text>
        )}
        {listState.type === "READY" &&
          listState.configs.map((toolkit) => (
            <ToolkitCard
              key={toolkit.id}
              toolkit={toolkit}
              basePath={basePath}
              onDelete={handleDeleteClick}
              onToggleEnabled={onToggleEnabled}
            />
          ))}

        <Modal
          opened={deleteOpened}
          onClose={closeDelete}
          title={t("delete")}
          centered
        >
          <Stack gap="md">
            <Text>{t("deleteConfirm")}</Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={closeDelete}>
                {t("cancel")}
              </Button>
              <Button color="red" onClick={handleDeleteConfirm}>
                {t("delete")}
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Stack>
    </Container>
  );
}

function ToolkitCard({
  toolkit,
  basePath,
  onDelete,
  onToggleEnabled,
}: {
  toolkit: ToolkitConfigResponse;
  basePath: string;
  onDelete: (toolkitId: string) => void;
  onToggleEnabled: (toolkit: ToolkitConfigResponse, enabled: boolean) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.toolkits");

  return (
    <Card withBorder padding="md">
      <Group justify="space-between" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="sm">
            <Badge variant="light" size="sm">
              {toolkit.toolkit_type}
            </Badge>
            {toolkit.slug && (
              <Badge variant="outline" size="sm">
                {toolkit.slug}
              </Badge>
            )}
            <Text fw={500} truncate>
              {toolkit.name}
            </Text>
            {!toolkit.enabled && (
              <Badge color="gray" variant="outline" size="sm">
                {t("disabled")}
              </Badge>
            )}
          </Group>
          {toolkit.description && (
            <Text size="sm" c="dimmed" lineClamp={1}>
              {toolkit.description}
            </Text>
          )}
          {toolkit.authorization_state?.status === "reconnect_required" && (
            <Alert
              color="red"
              variant="light"
              icon={<IconAlertTriangle size={16} />}
              title={t("github.reconnectRequiredTitle")}
            >
              <Text size="sm">
                {t("github.reconnectReasonAppIdentityChanged")}
              </Text>
            </Alert>
          )}
        </Stack>

        <Group gap="xs" wrap="nowrap">
          <Switch
            checked={toolkit.enabled}
            disabled={
              toolkit.authorization_state?.status === "reconnect_required" &&
              !toolkit.enabled
            }
            onChange={(e) => onToggleEnabled(toolkit, e.currentTarget.checked)}
            size="sm"
          />
          <ActionIcon
            component={Link}
            href={`${basePath}/${toolkit.id}/edit`}
            variant="subtle"
          >
            <IconEdit size={16} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={() => onDelete(toolkit.id)}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
      </Group>
    </Card>
  );
}
