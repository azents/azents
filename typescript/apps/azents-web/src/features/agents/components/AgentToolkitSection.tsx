"use client";

/** Saved-Agent management retains the existing non-administrator boundary. */
import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconLink, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { LegacyAgentToolkitSectionProps } from "../types";

export function LegacyAgentToolkitSection({
  state,
  selectedToolkitId,
  onSelectionChange,
  onAttach,
  onDetach,
}: LegacyAgentToolkitSectionProps): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const loading = state.type === "LOADING" || state.type === "LOADING_ERROR";
  const failed = state.type === "ERROR" || state.type === "LOADING_ERROR";
  const { agentToolkits, availableToolkits, selectOptions } = state;
  return (
    <Stack id="agent-toolkits" gap="sm">
      <Title order={5}>{t("toolkitsSection")}</Title>
      {loading && <Loader size="sm" />}
      {failed && <Alert color="red">{t("toolkitLoadError")}</Alert>}
      {!loading && !failed && agentToolkits.length === 0 && (
        <Text size="sm" c="dimmed">
          {t("noToolkitsAttached")}
        </Text>
      )}
      {agentToolkits.map((item) => (
        <Group key={item.id} gap="sm">
          <Badge variant="light" size="sm">
            {item.toolkit_type}
          </Badge>
          <Text size="sm" style={{ flex: 1 }}>
            {availableToolkits.find((toolkit) => toolkit.id === item.toolkit_id)
              ?.name ?? item.toolkit_id}
          </Text>
          <ActionIcon
            variant="subtle"
            color="red"
            size="sm"
            aria-label={t("toolkitManagement.detach")}
            onClick={() => onDetach(item.id)}
          >
            <IconTrash size={14} />
          </ActionIcon>
        </Group>
      ))}
      {!loading && !failed && selectOptions.length > 0 && (
        <Group gap="sm">
          <Select
            placeholder={t("attachToolkit")}
            data={selectOptions}
            value={selectedToolkitId}
            onChange={onSelectionChange}
            size="sm"
            style={{ flex: 1 }}
          />
          <ActionIcon
            variant="light"
            size="lg"
            aria-label={t("toolkitManagement.attach")}
            disabled={selectedToolkitId == null}
            onClick={() => {
              if (selectedToolkitId) {
                onAttach(selectedToolkitId);
              }
            }}
          >
            <IconLink size={16} />
          </ActionIcon>
        </Group>
      )}
      {!loading &&
        !failed &&
        selectOptions.length === 0 &&
        availableToolkits.length === 0 && (
          <Text size="sm" c="dimmed">
            {t("noToolkitsAvailable")}
          </Text>
        )}
    </Stack>
  );
}
