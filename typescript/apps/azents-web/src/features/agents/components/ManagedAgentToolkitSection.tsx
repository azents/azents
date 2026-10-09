"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  rem,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { IconArrowLeft, IconLock, IconPlus } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ToolkitTypeIcon } from "@/shared/toolkits/components/ToolkitTypeIcon";
import { isGitHubUserMode } from "@/shared/toolkits/github-user-oauth-state";
import { GitHubUserAuthorizationContainer } from "@/shared/toolkits/GitHubUserAuthorizationContainer";
import { projectToolkitDetails } from "@/shared/toolkits/toolkit-detail-projection";
import { ToolkitFormContainer } from "@/shared/toolkits/ToolkitFormContainer";
import { canAuthorizeAgentToolkitOAuth } from "../agentToolkitManagementState";
import type { AgentToolkitManagementContainerOutput } from "../containers/useAgentToolkitManagementContainer";
import type { AgentToolkitManagementItemResponse } from "@azents/public-client";
import type { ReactNode } from "react";

export interface ManagedToolkitCardProps {
  item: AgentToolkitManagementItemResponse;
  pending: boolean;
  canAuthorizeShared: boolean;
  authorizationPending: boolean;
  workspaceEditHref: string;
  onAuthorize: () => void;
  onDetails: () => void;
  onDetach: () => void;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  userConnectionView?: ReactNode;
}

function ToolkitIdentity({
  item,
}: {
  item: AgentToolkitManagementItemResponse;
}): React.ReactElement {
  return (
    <Group gap="sm" wrap="nowrap">
      <ToolkitTypeIcon toolkitType={item.toolkit.toolkit_type} />
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Text fw={600} style={{ overflowWrap: "anywhere" }}>
          {item.toolkit.name}
        </Text>
        <Text size="xs" c="dimmed">
          {item.toolkit.toolkit_type}
        </Text>
      </Stack>
    </Group>
  );
}

function ToolkitBadges({
  item,
}: {
  item: AgentToolkitManagementItemResponse;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.toolkitManagement");
  return (
    <Group gap="xs">
      <Badge
        variant="outline"
        color={item.ownership_scope === "workspace_shared" ? "blue" : "violet"}
      >
        {t(
          item.ownership_scope === "workspace_shared"
            ? "workspaceShared"
            : "agentOnly",
        )}
      </Badge>
      <Badge
        variant="light"
        color={
          item.readiness === "ready"
            ? "green"
            : item.readiness === "disabled"
              ? "gray"
              : "orange"
        }
      >
        {t(`readiness.${item.readiness}`)}
      </Badge>
    </Group>
  );
}

function AuthorizationAction({
  item,
  pending,
  authorizationPending,
  canAuthorizeShared,
  workspaceEditHref,
  onAuthorize,
  onEdit,
}: ManagedToolkitCardProps): React.ReactElement | null {
  const t = useTranslations("workspace.agents.toolkitManagement");
  if (
    item.readiness !== "authorization_required" ||
    (item.ownership_scope === "workspace_shared" && !canAuthorizeShared)
  ) {
    return null;
  }
  if (canAuthorizeAgentToolkitOAuth(item, canAuthorizeShared)) {
    return (
      <Button
        size="xs"
        variant="light"
        color="orange"
        leftSection={<IconLock size={14} />}
        loading={authorizationPending}
        disabled={pending || authorizationPending}
        onClick={onAuthorize}
      >
        {t(item.toolkit.oauth_connection == null ? "authorize" : "reauthorize")}
      </Button>
    );
  }
  return item.ownership_scope === "workspace_shared" ? (
    <Button size="xs" variant="light" component={Link} href={workspaceEditHref}>
      {t("reviewAuthorization")}
    </Button>
  ) : (
    <Button size="xs" variant="light" onClick={onEdit}>
      {t("reviewAuthorization")}
    </Button>
  );
}

export function ManagedToolkitCard(
  props: ManagedToolkitCardProps,
): React.ReactElement {
  const t = useTranslations("workspace.agents.toolkitManagement");
  return (
    <Card withBorder radius="md" p="md">
      <Stack gap="sm">
        <ToolkitIdentity item={props.item} />
        <ToolkitBadges item={props.item} />
        {props.item.toolkit.description && (
          <Text size="sm" c="dimmed" lineClamp={1}>
            {props.item.toolkit.description}
          </Text>
        )}
        <Group
          justify="flex-end"
          mt="xs"
          pt="xs"
          style={{
            borderTop: `${rem(1)} solid var(--mantine-color-default-border)`,
          }}
        >
          <Button
            variant="subtle"
            size="xs"
            onClick={props.onDetails}
            disabled={props.pending || props.authorizationPending}
          >
            {t("catalog.details")}
          </Button>
          <AuthorizationAction {...props} />
        </Group>
      </Stack>
    </Card>
  );
}

export function ToolkitConnectionDetails(
  props: ManagedToolkitCardProps,
): React.ReactElement {
  const t = useTranslations("workspace.agents.toolkitManagement");
  const shared = props.item.ownership_scope === "workspace_shared";
  const fields = projectToolkitDetails(props.item.toolkit);
  return (
    <Stack gap="lg">
      <ToolkitIdentity item={props.item} />
      <ToolkitBadges item={props.item} />
      {props.item.toolkit.description && (
        <Text size="sm">{props.item.toolkit.description}</Text>
      )}
      <Stack gap="xs">
        {fields.map((field) => (
          <Group key={field.label} align="flex-start" wrap="nowrap">
            <Text size="sm" c="dimmed" w={rem(120)} style={{ flexShrink: 0 }}>
              {t(`catalog.fields.${field.label}`)}
            </Text>
            <Text size="sm" style={{ overflowWrap: "anywhere", minWidth: 0 }}>
              {field.value}
            </Text>
          </Group>
        ))}
      </Stack>
      <Text size="xs" c="dimmed">
        {t("catalog.permissionHint")}
      </Text>
      {props.userConnectionView}
      <Text size="xs" c="dimmed">
        {t("catalog.readinessHint")}
      </Text>
      <Text size="sm" c="dimmed">
        {shared
          ? props.canAuthorizeShared
            ? t("workspaceBoundary")
            : t("workspaceAuthorizationRestricted")
          : t("agentOnlyDescription")}
      </Text>
      <Group gap="xs">
        <AuthorizationAction {...props} />
        {shared ? (
          <>
            {props.canAuthorizeShared && (
              <Button
                variant="default"
                component={Link}
                href={props.workspaceEditHref}
              >
                {t("catalog.manageWorkspace")}
              </Button>
            )}
            <Button
              variant="subtle"
              color="red"
              disabled={props.pending || props.authorizationPending}
              onClick={props.onDetach}
            >
              {t("detach")}
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="default"
              disabled={props.pending || props.authorizationPending}
              onClick={props.onEdit}
            >
              {t("edit")}
            </Button>
            <Button
              variant="default"
              disabled={props.pending || props.authorizationPending}
              onClick={props.onToggle}
            >
              {t(props.item.toolkit.enabled ? "disable" : "enable")}
            </Button>
            <Button
              variant="subtle"
              color="red"
              disabled={props.pending || props.authorizationPending}
              onClick={props.onDelete}
            >
              {t("delete")}
            </Button>
          </>
        )}
      </Group>
    </Stack>
  );
}

interface CatalogTileProps {
  name: string;
  toolkitType: string;
  description?: string | null;
  disabled: boolean;
  pending?: boolean;
  providerName?: string;
  onClick: () => void;
}

function CatalogTile({
  name,
  toolkitType,
  description,
  disabled,
  pending,
  providerName,
  onClick,
}: CatalogTileProps): React.ReactElement {
  return (
    <Card
      component="button"
      type="button"
      onClick={onClick}
      disabled={disabled}
      withBorder
      radius="md"
      p="md"
      style={{ textAlign: "start", opacity: disabled ? 0.6 : 1 }}
    >
      <Stack gap="sm">
        <Group justify="space-between">
          <ToolkitTypeIcon toolkitType={toolkitType} />
          {pending && <Loader size="xs" />}
        </Group>
        <Text fw={600} size="sm" style={{ overflowWrap: "anywhere" }}>
          {name}
        </Text>
        {providerName && (
          <Text size="xs" c="dimmed">
            {providerName}
          </Text>
        )}
        {description && (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {description}
          </Text>
        )}
      </Stack>
    </Card>
  );
}

export function ManagedAgentToolkitSectionView(
  props: AgentToolkitManagementContainerOutput & {
    setupView?: ReactNode;
    githubUserView?: ReactNode;
  },
): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const { editor, state } = props;
  const detailId = editor.type === "DETAIL" ? editor.toolkitConfigId : null;
  const selectedItem =
    state.type === "READY"
      ? (state.items.find((item) => item.toolkit.id === detailId) ?? null)
      : null;
  function cardProps(
    item: AgentToolkitManagementItemResponse,
  ): ManagedToolkitCardProps {
    return {
      item,
      pending: props.pending || props.setupPending,
      canAuthorizeShared: props.canAuthorizeShared,
      authorizationPending: props.authorizationPendingId === item.toolkit.id,
      workspaceEditHref: `/w/${props.handle}/toolkits/${item.toolkit.id}/edit`,
      onAuthorize: () => props.onAuthorize(item),
      onDetails: () => props.onDetails(item.toolkit.id),
      onDetach: () => {
        if (item.agent_toolkit_id) {
          props.onDetach(item.agent_toolkit_id);
        }
      },
      onEdit: () => props.onEdit(item.toolkit.id),
      onToggle: () => props.onToggle(item),
      onDelete: () => props.onRequestDelete(item),
      userConnectionView:
        item.toolkit.toolkit_type === "github" &&
        isGitHubUserMode(item.toolkit.config.github_auth_type) &&
        (item.ownership_scope === "agent_only" || props.canAuthorizeShared) &&
        editor.type === "DETAIL" &&
        editor.toolkitConfigId === item.toolkit.id
          ? (props.githubUserView ?? (
              <GitHubUserAuthorizationContainer
                key={item.toolkit.id}
                toolkit={item.toolkit}
                context={{
                  handle: props.handle,
                  toolkitId: item.toolkit.id,
                  ...(item.ownership_scope === "agent_only" && {
                    agentId: props.agentId,
                  }),
                  returnView: "DETAIL",
                  returnPath: `/w/${props.handle}/agents/${props.agentId}/settings/capabilities#agent-toolkits`,
                }}
                initialPopup={
                  props.githubUserPopup?.toolkitId === item.toolkit.id
                    ? props.githubUserPopup.popup
                    : null
                }
                onPendingChange={props.onSetupPendingChange}
                onInitialPopupAccepted={props.onGithubUserPopupAccepted}
              />
            ))
          : null,
    };
  }
  const modalTitle =
    editor.type === "DETAIL"
      ? t("toolkitManagement.catalog.details")
      : editor.type === "CREATE" || editor.type === "EDIT"
        ? t("toolkitManagement.catalog.configure")
        : t("toolkitManagement.addToolkit");
  return (
    <Stack id="agent-toolkits" gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={5}>{t("toolkitsSection")}</Title>
          <Text size="sm" c="dimmed">
            {t("toolkitManagement.catalog.immediateSave")}
          </Text>
        </Stack>
        <Button
          size="xs"
          leftSection={<IconPlus size={14} />}
          disabled={state.type !== "READY"}
          onClick={props.onStartAdd}
        >
          {t("toolkitManagement.addToolkit")}
        </Button>
      </Group>
      {state.type === "LOADING" && <Loader size="sm" />}
      {state.type === "ERROR" && (
        <Alert color="red">
          <Stack gap="xs">
            <Text size="sm">{state.message || t("toolkitLoadError")}</Text>
            <Button
              variant="light"
              size="xs"
              w="fit-content"
              onClick={props.onRetryRead}
            >
              {t("toolkitManagement.catalog.retryRead")}
            </Button>
          </Stack>
        </Alert>
      )}
      {props.mutationState.type === "ERROR" && editor.type === "CLOSED" && (
        <Alert color="red">{props.mutationState.message}</Alert>
      )}
      {state.type === "READY" &&
        (state.items.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t("noToolkitsAttached")}
          </Text>
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
            {state.items.map((item) => (
              <ManagedToolkitCard
                key={`${item.ownership_scope}:${item.toolkit.id}`}
                {...cardProps(item)}
              />
            ))}
          </SimpleGrid>
        ))}
      <Modal
        opened={editor.type !== "CLOSED" && props.deleteTarget == null}
        onClose={props.onCloseEditor}
        title={modalTitle}
        size="lg"
        centered
        closeOnClickOutside={false}
        withCloseButton={!props.setupPending && !props.attachPending}
        closeOnEscape={
          !props.pending && !props.attachPending && !props.setupPending
        }
      >
        <Stack gap="md">
          {props.mutationState.type === "ERROR" && (
            <Alert color="red">{props.mutationState.message}</Alert>
          )}
          {editor.type === "CATALOG" && (
            <Tabs
              value={editor.tab}
              onChange={(tab) => {
                if (
                  (tab === "new" || tab === "workspace") &&
                  !props.attachPending
                ) {
                  props.onCatalogTabChange(tab);
                }
              }}
            >
              <Tabs.List grow>
                <Tabs.Tab value="new">
                  {t("toolkitManagement.catalog.newTab")}
                </Tabs.Tab>
                <Tabs.Tab value="workspace">
                  {t("toolkitManagement.catalog.workspaceTab")}
                </Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="new" pt="md">
                <Stack gap="md">
                  <Text size="sm" c="dimmed">
                    {t("toolkitManagement.agentOnlyDescription")}
                  </Text>
                  {state.type === "READY" && (
                    <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
                      {state.toolkitTypes.map((type) => (
                        <CatalogTile
                          key={type.value}
                          name={type.label}
                          toolkitType={type.value}
                          disabled={props.attachPending}
                          onClick={() => props.onConfigureType(type.value)}
                        />
                      ))}
                    </SimpleGrid>
                  )}
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="workspace" pt="md">
                <Stack gap="md">
                  <Text size="sm" c="dimmed">
                    {t("toolkitManagement.attachSharedDescription")}
                  </Text>
                  {state.type === "READY" && (
                    <>
                      {state.availableShared.length === 0 && (
                        <Text size="sm" c="dimmed">
                          {t("toolkitManagement.catalog.noShared")}
                        </Text>
                      )}
                      <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
                        {state.availableShared.map((item) => (
                          <CatalogTile
                            key={item.value}
                            name={item.label}
                            toolkitType={item.toolkitType}
                            providerName={
                              state.toolkitTypes.find(
                                (type) => type.value === item.toolkitType,
                              )?.label ?? item.toolkitType
                            }
                            description={item.description}
                            disabled={props.attachPending}
                            pending={props.attachPendingId === item.value}
                            onClick={() => props.onAttach(item.value)}
                          />
                        ))}
                        <Card
                          withBorder
                          radius="md"
                          p="md"
                          component={Link}
                          href={`/w/${props.handle}/toolkits/new`}
                          style={{
                            textDecoration: "none",
                            borderStyle: "dashed",
                          }}
                        >
                          <Stack
                            align="center"
                            justify="center"
                            gap="sm"
                            h="100%"
                          >
                            <IconPlus size={24} />
                            <Text size="sm" fw={600} ta="center">
                              {t("toolkitManagement.catalog.addWorkspace")}
                            </Text>
                            <Text size="xs" c="dimmed" ta="center">
                              {t("toolkitManagement.catalog.workspaceRedirect")}
                            </Text>
                          </Stack>
                        </Card>
                      </SimpleGrid>
                    </>
                  )}
                </Stack>
              </Tabs.Panel>
            </Tabs>
          )}
          {(editor.type === "CREATE" || editor.type === "EDIT") && (
            <>
              <Button
                variant="subtle"
                leftSection={<IconArrowLeft size={14} />}
                w="fit-content"
                disabled={props.setupPending}
                onClick={() =>
                  editor.type === "CREATE"
                    ? props.onCatalogTabChange("new")
                    : props.onDetails(editor.toolkitConfigId)
                }
              >
                {t("toolkitManagement.catalog.back")}
              </Button>
              {props.setupView ?? (
                <ToolkitFormContainer
                  handle={props.handle}
                  agentId={props.agentId}
                  embedded
                  onComplete={props.onCompleteSetup}
                  onPendingChange={props.onSetupPendingChange}
                  {...(editor.type === "CREATE"
                    ? { initialToolkitType: editor.toolkitType }
                    : { toolkitId: editor.toolkitConfigId })}
                />
              )}
            </>
          )}
          {editor.type === "DETAIL" &&
            (selectedItem ? (
              <ToolkitConnectionDetails {...cardProps(selectedItem)} />
            ) : state.type === "LOADING" ? (
              <Loader size="sm" />
            ) : (
              <Alert>{t("toolkitManagement.catalog.unavailable")}</Alert>
            ))}
          {state.type === "ERROR" && (
            <Alert color="red">
              <Stack gap="xs">
                <Text size="sm">{state.message}</Text>
                <Button
                  variant="light"
                  size="xs"
                  w="fit-content"
                  onClick={props.onRetryRead}
                >
                  {t("toolkitManagement.catalog.retryRead")}
                </Button>
              </Stack>
            </Alert>
          )}
        </Stack>
      </Modal>
      <Modal
        opened={props.deleteTarget != null}
        onClose={props.onCancelDelete}
        title={t("toolkitManagement.deleteTitle")}
        centered
      >
        <Stack>
          {props.mutationState.type === "ERROR" && (
            <Alert color="red">{props.mutationState.message}</Alert>
          )}
          <Text size="sm">
            {t("toolkitManagement.deleteDescription", {
              name: props.deleteTarget?.toolkit.name ?? "",
            })}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={props.onCancelDelete}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              loading={props.deletePending}
              onClick={props.onConfirmDelete}
            >
              {t("toolkitManagement.deleteConfirm")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
