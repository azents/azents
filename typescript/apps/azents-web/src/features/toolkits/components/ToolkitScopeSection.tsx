"use client";

/**
 * Toolkit Scope management section.
 *
 * Displays workspace visibility assigned to Toolkit and adds/deletes it.
 */

import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { ScopeListState } from "../types";

interface ToolkitScopeSectionProps {
  scopeListState: ScopeListState;
  onAddScope: () => void;
  onDeleteScope: (scopeId: string) => void;
}

export function ToolkitScopeSection({
  scopeListState,
  onAddScope,
  onDeleteScope,
}: ToolkitScopeSectionProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits");

  return (
    <Stack gap="sm">
      <Title order={5}>{t("scopesSection")}</Title>

      {scopeListState.type === "LOADING" && <Loader size="sm" />}

      {scopeListState.type === "READY" && (
        <>
          {scopeListState.scopes.length === 0 && (
            <Text size="sm" c="dimmed">
              {t("noScopes")}
            </Text>
          )}
          {scopeListState.scopes.map((scope) => (
            <Group key={scope.id} gap="sm">
              <Badge variant="light" size="sm">
                {t("scopeWorkspace")}
              </Badge>
              <Text size="sm" style={{ flex: 1 }}>
                {scope.scope_id}
              </Text>
              <ActionIcon
                variant="subtle"
                color="red"
                size="sm"
                onClick={() => onDeleteScope(scope.id)}
              >
                <IconTrash size={14} />
              </ActionIcon>
            </Group>
          ))}
        </>
      )}

      <Button
        size="sm"
        variant="light"
        leftSection={<IconPlus size={14} />}
        onClick={onAddScope}
        disabled={
          scopeListState.type !== "READY" || scopeListState.scopes.length > 0
        }
      >
        {t("addWorkspaceScope")}
      </Button>
    </Stack>
  );
}
