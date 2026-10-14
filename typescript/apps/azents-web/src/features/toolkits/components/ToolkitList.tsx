"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  Group,
  Loader,
  Modal,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import {
  IconArrowLeft,
  IconArrowRight,
  IconPlus,
  IconUsers,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { ToolkitTypeIcon } from "@/shared/toolkits/components/ToolkitTypeIcon";
import { GITHUB_FEATURE_GROUPS } from "@/shared/toolkits/github-wizard-state";
import { projectToolkitDetails } from "@/shared/toolkits/toolkit-detail-projection";
import { usesToolkitCreationWizard } from "@/shared/toolkits/toolkit-form-lifecycle";
import { ToolkitFormContainer } from "@/shared/toolkits/ToolkitFormContainer";
import {
  canToggleWorkspaceToolkit,
  toolkitNeedsReauthorization,
  workspaceToolkitEditorPending,
} from "../workspace-toolkit-management-state";
import classes from "./ToolkitList.module.css";
import type { ToolkitListContainerOutput } from "../containers/useToolkitListContainer";
import type { ToolkitDetailField } from "@/shared/toolkits/toolkit-detail-projection";
import type { ToolkitConfigResponse } from "@azents/public-client";
import type { ReactElement, ReactNode } from "react";

interface ToolkitListProps extends ToolkitListContainerOutput {
  /** Static component stories can replace API-owning form composition. */
  setupView?: ReactNode;
}

function ToolkitBadges({
  toolkit,
}: {
  toolkit: ToolkitConfigResponse;
}): ReactElement {
  const t = useTranslations("workspace.toolkits.management");
  return (
    <Group gap="xs">
      <Badge variant="light" color={toolkit.enabled ? "mono" : "gray"}>
        {t(toolkit.enabled ? "enabled" : "disabled")}
      </Badge>
      {toolkitNeedsReauthorization(toolkit) && (
        <Badge
          variant="light"
          color="orange"
          className={classes.warningText}
          data-workspace-reauthorization
        >
          {t("reauthorizationRequired")}
        </Badge>
      )}
    </Group>
  );
}

function ToolkitDetailValue({
  field,
  toolkitType,
}: {
  field: ToolkitDetailField;
  toolkitType: string;
}): ReactElement {
  const t = useTranslations("workspace.toolkits.management");
  const feature = useTranslations(
    "workspace.toolkits.github.wizard.featureNames",
  );
  let value = field.value;
  if (
    ["runtimeInjection", "readOnly"].includes(field.label) &&
    ["true", "false"].includes(value)
  ) {
    value = t(value === "true" ? "settingOn" : "settingOff");
  }
  if (field.label === "authType") {
    const authLabels: Record<string, string> = {
      github_app: t("authTypes.github_app"),
      github_app_user: t("authTypes.github_app_user"),
      github_app_platform: t("authTypes.github_app_platform"),
      github_app_platform_user: t("authTypes.github_app_platform_user"),
      pat: "Personal Access Token",
      oauth2: "OAuth 2.0",
    };
    value = authLabels[value] ?? value;
  }
  if (field.label === "features" && toolkitType === "github") {
    value = value
      .split(", ")
      .map((name) => {
        const group = GITHUB_FEATURE_GROUPS.find((item) => item === name);
        return group ? feature(group) : name;
      })
      .join(" · ");
  }
  return <Text size="sm">{value}</Text>;
}

export function ToolkitList(props: ToolkitListProps): ReactElement {
  function providerName(toolkitType: string): string {
    return props.catalogState.type === "READY"
      ? (props.catalogState.toolkits.find((type) => type.slug === toolkitType)
          ?.name ?? toolkitType)
      : toolkitType;
  }
  const t = useTranslations("workspace.toolkits");
  const m = useTranslations("workspace.toolkits.management");
  const detail = useTranslations("workspace.agents.toolkitManagement.catalog");
  const selectedId =
    props.editor.type === "DETAIL" || props.editor.type === "EDIT"
      ? props.editor.toolkitId
      : null;
  const selected =
    props.listState.type === "READY"
      ? props.listState.configs.find((item) => item.id === selectedId)
      : null;
  const deleteToolkit =
    props.listState.type === "READY"
      ? props.listState.configs.find((item) => item.id === props.deleteTarget)
      : null;
  const formPending = workspaceToolkitEditorPending(
    props.editor,
    props.setupPending,
    props.createPublicationPending,
  );
  const blocked = props.pending || formPending;
  const newWizard =
    props.editor.type === "CREATE" &&
    usesToolkitCreationWizard(props.editor.toolkitType);
  return (
    <Container size="lg" py="xl">
      <Stack gap="lg">
        <Group justify="space-between" align="flex-start">
          <div>
            <Title order={3}>{m("headline")}</Title>
            <Text c="dimmed" size="sm" mt="xs">
              {m("description")}
            </Text>
          </div>
          <Button
            leftSection={<IconPlus size="1em" />}
            onClick={props.onStartAdd}
            disabled={blocked}
          >
            {t("addToolkit")}
          </Button>
        </Group>
        <Group gap="xs">
          <IconUsers size="1em" aria-hidden />
          <Text size="sm" fw={500}>
            {m("sharedScope")}
          </Text>
          <Text size="sm" c="dimmed">
            {m("sharedHint")}
          </Text>
        </Group>
        {props.refreshFailed && (
          <Alert color="yellow">
            <Stack gap="xs">
              <Text size="sm">{m("refreshFailed")}</Text>
              <Button
                variant="default"
                size="xs"
                w="fit-content"
                onClick={props.onRetryRead}
              >
                {m("retryRead")}
              </Button>
            </Stack>
          </Alert>
        )}
        {props.writeState.type === "ERROR" &&
          props.editor.type === "CLOSED" && (
            <Alert color="red">{props.writeState.message}</Alert>
          )}
        {props.listState.type === "LOADING" && <Loader size="sm" />}
        {props.listState.type === "ERROR" && (
          <Alert color="red">
            <Stack gap="xs">
              <Text size="sm">{t("loadError")}</Text>
              <Button
                variant="default"
                size="xs"
                w="fit-content"
                onClick={props.onRetryRead}
              >
                {m("retryRead")}
              </Button>
            </Stack>
          </Alert>
        )}
        {props.listState.type === "READY" &&
          (props.listState.configs.length === 0 ? (
            <Stack align="flex-start" py="xl">
              <Text fw={500}>{t("empty")}</Text>
              <Button
                variant="default"
                onClick={props.onStartAdd}
                disabled={blocked}
              >
                {t("addToolkit")}
              </Button>
            </Stack>
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
              {props.listState.configs.map((toolkit) => (
                <Card
                  key={toolkit.id}
                  component="article"
                  aria-label={toolkit.name}
                  withBorder
                  radius="md"
                  padding="lg"
                  className={classes.card}
                >
                  <Stack gap="xs">
                    <ToolkitTypeIcon toolkitType={toolkit.toolkit_type} />
                    <Text size="xs" c="dimmed">
                      {providerName(toolkit.toolkit_type)}
                    </Text>
                    <Text fw={600} className={classes.name}>
                      {toolkit.name}
                    </Text>
                    {toolkit.description && (
                      <Text size="sm" c="dimmed" className={classes.name}>
                        {toolkit.description}
                      </Text>
                    )}
                  </Stack>
                  <ToolkitBadges toolkit={toolkit} />
                  <Group justify="flex-end" gap="xs" className={classes.footer}>
                    {toolkitNeedsReauthorization(toolkit) && (
                      <Button
                        variant="light"
                        color="orange"
                        className={classes.warningText}
                        data-workspace-reauthorization
                        size="xs"
                        disabled={blocked}
                        onClick={() => props.onEdit(toolkit.id)}
                      >
                        {m("reviewAuthorization")}
                      </Button>
                    )}
                    <Button
                      variant="subtle"
                      size="xs"
                      rightSection={<IconArrowRight size="1em" />}
                      disabled={blocked}
                      onClick={() => props.onDetails(toolkit.id)}
                    >
                      {m("details")}
                    </Button>
                  </Group>
                </Card>
              ))}
            </SimpleGrid>
          ))}
      </Stack>
      <Modal
        opened={props.editor.type !== "CLOSED" && props.deleteTarget == null}
        onClose={props.onCloseEditor}
        title={
          props.editor.type === "DETAIL"
            ? m("detailTitle")
            : props.editor.type === "CREATE" || props.editor.type === "EDIT"
              ? m("configureTitle")
              : m("catalogTitle")
        }
        size={
          props.editor.type === "CREATE" || props.editor.type === "EDIT"
            ? "xl"
            : "lg"
        }
        centered
        closeOnClickOutside={false}
        closeOnEscape={!blocked}
        withCloseButton={!blocked}
        closeButtonProps={{ "aria-label": t("github.wizard.close") }}
      >
        <Stack gap="md">
          {props.writeState.type === "ERROR" && (
            <Alert color="red">{props.writeState.message}</Alert>
          )}
          {props.refreshFailed && (
            <Alert color="yellow">
              <Stack gap="xs">
                <Text size="sm">{m("refreshFailed")}</Text>
                <Button
                  variant="default"
                  size="xs"
                  w="fit-content"
                  onClick={props.onRetryRead}
                >
                  {m("retryRead")}
                </Button>
              </Stack>
            </Alert>
          )}
          {props.editor.type === "CATALOG" && (
            <Stack gap="md">
              <Text size="sm" c="dimmed">
                {m("catalogHint")}
              </Text>
              {props.catalogState.type === "LOADING" && <Loader size="sm" />}
              {props.catalogState.type === "ERROR" && (
                <Alert color="red">
                  <Stack>
                    <Text size="sm">{m("catalogError")}</Text>
                    <Button
                      variant="default"
                      w="fit-content"
                      onClick={props.onRetryRead}
                    >
                      {m("retryRead")}
                    </Button>
                  </Stack>
                </Alert>
              )}
              {props.catalogState.type === "READY" && (
                <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
                  {props.catalogState.toolkits.map((type) => (
                    <UnstyledButton
                      key={type.slug}
                      className={classes.provider}
                      onClick={() => props.onConfigureType(type.slug)}
                    >
                      <ToolkitTypeIcon toolkitType={type.slug} />
                      <Text fw={600}>{type.name}</Text>
                      <Text size="sm" c="dimmed">
                        {type.description}
                      </Text>
                    </UnstyledButton>
                  ))}
                </SimpleGrid>
              )}
            </Stack>
          )}
          {(props.editor.type === "CREATE" || props.editor.type === "EDIT") && (
            <>
              <Button
                variant="subtle"
                leftSection={<IconArrowLeft size="1em" />}
                w="fit-content"
                disabled={blocked}
                onClick={props.onBack}
              >
                {m("back")}
              </Button>
              {props.setupView ?? (
                <ToolkitFormContainer
                  key={
                    props.editor.type === "CREATE"
                      ? `create:${props.editor.toolkitType}`
                      : `edit:${props.editor.toolkitId}`
                  }
                  handle={props.handle}
                  embedded
                  onComplete={props.onCompleteSetup}
                  onPendingChange={
                    newWizard
                      ? props.onCreatePublicationPendingChange
                      : props.onSetupPendingChange
                  }
                  onAbandonReady={props.onCreateAbandonReady}
                  {...(props.editor.type === "CREATE"
                    ? { initialToolkitType: props.editor.toolkitType }
                    : { toolkitId: props.editor.toolkitId })}
                />
              )}
            </>
          )}
          {props.editor.type === "DETAIL" &&
            (selected ? (
              <Stack gap="lg">
                <Stack gap="xs">
                  <ToolkitTypeIcon toolkitType={selected.toolkit_type} />
                  <Title order={4} className={classes.name}>
                    {selected.name}
                  </Title>
                  <ToolkitBadges toolkit={selected} />
                  <Text size="sm" c="dimmed">
                    {m("sharedScope")} · {m("sharedHint")}
                  </Text>
                  {selected.description && (
                    <Text size="sm" c="dimmed">
                      {selected.description}
                    </Text>
                  )}
                </Stack>
                <dl className={classes.fields}>
                  {projectToolkitDetails(selected).map((field) => (
                    <div key={field.label} style={{ display: "contents" }}>
                      <dt>
                        <Text size="sm">{detail(`fields.${field.label}`)}</Text>
                      </dt>
                      <dd>
                        <ToolkitDetailValue
                          field={field}
                          toolkitType={selected.toolkit_type}
                        />
                      </dd>
                    </div>
                  ))}
                </dl>
                <Text size="xs" c="dimmed">
                  {detail("permissionHint")}
                </Text>
                <Text size="xs" c="dimmed">
                  {m("stateHint")}
                </Text>
                <Switch
                  label={m("enabledLabel")}
                  checked={selected.enabled}
                  disabled={
                    blocked ||
                    !canToggleWorkspaceToolkit(selected, !selected.enabled)
                  }
                  onChange={(event) =>
                    props.onToggleEnabled(selected, event.currentTarget.checked)
                  }
                />
                <Group justify="space-between" align="flex-start">
                  <Group gap="xs">
                    <Button
                      variant="default"
                      disabled={blocked}
                      onClick={() => props.onEdit(selected.id)}
                    >
                      {m("edit")}
                    </Button>
                    {toolkitNeedsReauthorization(selected) && (
                      <Button
                        variant="light"
                        color="orange"
                        className={classes.warningText}
                        data-workspace-reauthorization
                        disabled={blocked}
                        onClick={() => props.onEdit(selected.id)}
                      >
                        {m("reviewAuthorization")}
                      </Button>
                    )}
                  </Group>
                  <Button
                    variant="subtle"
                    color="red"
                    disabled={blocked}
                    onClick={() => props.onDelete(selected.id)}
                  >
                    {t("delete")}
                  </Button>
                </Group>
              </Stack>
            ) : props.listState.type === "LOADING" ? (
              <Loader size="sm" />
            ) : (
              <Alert color="red">
                <Stack>
                  <Text size="sm">{m("unavailable")}</Text>
                  <Button
                    variant="default"
                    w="fit-content"
                    onClick={props.onRetryRead}
                  >
                    {m("retryRead")}
                  </Button>
                </Stack>
              </Alert>
            ))}
        </Stack>
      </Modal>
      <Modal
        opened={props.deleteTarget != null}
        onClose={props.onCancelDelete}
        closeOnEscape={props.deleteState.type !== "PENDING"}
        closeOnClickOutside={false}
        withCloseButton={props.deleteState.type !== "PENDING"}
        closeButtonProps={{ "aria-label": t("github.wizard.close") }}
        title={t("delete")}
        centered
      >
        <Stack gap="md">
          {props.deleteState.type === "ERROR" && (
            <Alert color="red">{props.deleteState.message}</Alert>
          )}
          {deleteToolkit && <Text fw={600}>{deleteToolkit.name}</Text>}
          <Text>{t("deleteConfirm")}</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={props.onCancelDelete}
              disabled={props.deleteState.type === "PENDING"}
            >
              {t("cancel")}
            </Button>
            <Button
              color="red"
              onClick={props.onConfirmDelete}
              loading={props.deleteState.type === "PENDING"}
            >
              {t("delete")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Container>
  );
}
