"use client";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  Container,
  Divider,
  Group,
  Loader,
  NumberInput,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { googleGroupPresets } from "../google-access";
import { googleServiceSchema } from "../google-schemas";
import classes from "./GoogleSetup.module.css";
import { ToolkitDisconnectConfirmation } from "./ToolkitDisconnectConfirmation";
import { ToolkitTypeIcon } from "./ToolkitTypeIcon";
import type { GoogleSetupProps } from "../google-types";
import type { GoogleReview } from "@azents/public-client";

function PermissionResult({
  review,
  props,
}: {
  review: GoogleReview;
  props: GoogleSetupProps;
}): React.ReactElement {
  const t = useTranslations("googleToolkit");
  const catalog =
    props.preparation.type === "READY"
      ? props.preparation.detail.tool_group_catalog
      : [];
  return (
    <Stack gap="md" role="group" aria-label={t("finalGroupsTitle")}>
      {catalog
        .filter(
          (group) =>
            review.services.includes(group.service) &&
            review.tool_groups.includes(group.group),
        )
        .map((group) => {
          const access = review.accesses.find(
            (item) => item.service === group.service,
          );
          const permitted = group.operations.filter((op) =>
            access?.permitted_tools.includes(op),
          );
          return (
            <Stack gap="xs" key={group.group}>
              <Group justify="space-between">
                <Text fw={500}>{t(`groups.${group.group}`)}</Text>
                <Badge
                  color={
                    permitted.length === group.operations.length
                      ? "green"
                      : permitted.length === 0
                        ? "gray"
                        : "yellow"
                  }
                >
                  {t("groupResult", {
                    available: permitted.length,
                    total: group.operations.length,
                  })}
                </Badge>
              </Group>
              {permitted.length < group.operations.length && (
                <Text size="xs" c="dimmed">
                  {t("groupUnavailable")}
                </Text>
              )}
              <details>
                <summary>{t("permissionDetails")}</summary>
                <Stack gap="xs" mt="sm">
                  {group.operations.map((op) => (
                    <Text key={op} size="xs">
                      <Code className={classes.code}>{op}</Code>
                      {" — "}
                      {t(
                        permitted.includes(op)
                          ? "access.permitted"
                          : "access.not_granted",
                      )}
                    </Text>
                  ))}
                </Stack>
              </details>
            </Stack>
          );
        })}
    </Stack>
  );
}
export function GoogleSetup(props: GoogleSetupProps): React.ReactElement {
  const t = useTranslations("googleToolkit"),
    common = useTranslations("workspace.toolkits");
  const { preparation, saved, flow } = props;
  const review =
    flow.type === "REVIEW" || flow.type === "CONFIRMING" ? flow.review : null;
  const busy =
    flow.type === "AUTHORIZING" ||
    flow.type === "VERIFYING" ||
    flow.type === "CONFIRMING" ||
    props.cancelling ||
    props.disconnecting ||
    props.savingServices;
  const editable = flow.type === "SELECT" || flow.type === "COMPLETE";
  const catalog =
    preparation.type === "READY" ? preparation.detail.tool_group_catalog : [];
  const unavailable =
    preparation.type !== "READY" ||
    preparation.detail.status !== "configured_unverified" ||
    saved.type === "LOADING" ||
    saved.type === "ERROR";
  const selectable =
    props.services.length > 0 &&
    catalog.some(
      (group) =>
        props.services.includes(group.service) &&
        props.toolGroups.includes(group.group),
    );
  return (
    <Container
      size="md"
      w="100%"
      miw={0}
      px={props.embedded ? 0 : "md"}
      py={props.embedded ? 0 : "lg"}
    >
      <Stack gap="lg" ref={props.rootRef}>
        <Group gap="sm">
          <ToolkitTypeIcon toolkitType="google" />
          <Stack gap={0}>
            <Title order={3}>
              {t(props.reconnect ? "editTitle" : "title")}
            </Title>
            <Text size="xs" c="dimmed">
              {t(
                props.ownership === "user"
                  ? "personalScope"
                  : props.ownership === "agent"
                    ? "agentScope"
                    : "sharedScope",
              )}
            </Text>
          </Stack>
        </Group>
        {props.operationError != null && (
          <Alert color="red" role="alert">
            {props.operationError}
          </Alert>
        )}
        {saved.type === "LOADING" && <Loader size="sm" />}
        {saved.type === "ERROR" && (
          <Alert color="red" role="alert">
            {saved.message}
            <Button variant="subtle" onClick={props.onRefresh}>
              {t("reload")}
            </Button>
          </Alert>
        )}
        {saved.type === "READY" && (
          <Stack gap="sm">
            <Group justify="space-between" align="flex-start">
              <Stack gap="xs" miw={0}>
                <Text fw={600} className={classes.identity}>
                  {saved.detail.identity?.email ??
                    saved.detail.identity?.subject ??
                    t("savedAccount")}
                </Text>
                <Group gap="xs">
                  <Badge
                    color={
                      saved.detail.status === "connected" ? "green" : "orange"
                    }
                  >
                    {t(`connection.${saved.detail.status}`)}
                  </Badge>
                </Group>
              </Stack>
              {editable && (
                <Button
                  leftSection={<IconRefresh size="1rem" />}
                  onClick={props.onReauthenticate}
                  disabled={busy || unavailable}
                >
                  {t("reauthenticate")}
                </Button>
              )}
            </Group>
            <Divider />
          </Stack>
        )}
        {preparation.type === "LOADING" ? (
          <Loader size="sm" />
        ) : preparation.type === "ERROR" ? (
          <Alert color="red" role="alert">
            {preparation.message}
            <Button variant="subtle" onClick={props.onRefresh}>
              {t("reload")}
            </Button>
          </Alert>
        ) : preparation.detail.status !== "configured_unverified" ? (
          <Alert color="yellow" title={t("operatorRequired")}>
            <Text size="sm">{t("operatorDescription")}</Text>
            <Button variant="subtle" onClick={props.onRefresh}>
              {t("reload")}
            </Button>
          </Alert>
        ) : null}
        {flow.type === "COMPLETE" && (
          <Alert
            color={flow.outcome.current ? "green" : "yellow"}
            title={t(flow.outcome.current ? "saved" : "superseded")}
            role="status"
          >
            <Text size="sm">
              {t(
                flow.outcome.current
                  ? "savedDescription"
                  : "supersededDescription",
              )}
            </Text>
          </Alert>
        )}
        {(flow.type === "AUTHORIZING" ||
          flow.type === "VERIFYING" ||
          flow.type === "CONFIRMING") && (
          <Group role="status">
            <Loader size="sm" />
            <Text>
              {t(
                flow.type === "AUTHORIZING"
                  ? "authorizing"
                  : flow.type === "VERIFYING"
                    ? "verifying"
                    : "applying",
              )}
            </Text>
          </Group>
        )}
        {flow.type === "ERROR" && (
          <Alert color="red" role="alert" title={t("failed")}>
            <Text>{flow.message}</Text>
            <Button
              mt="sm"
              leftSection={<IconRefresh size="1rem" />}
              onClick={() => {
                void props.onRetryAuthorization();
              }}
            >
              {t("reauthenticate")}
            </Button>
          </Alert>
        )}
        {flow.type === "UNKNOWN" && (
          <Alert color="yellow" title={t("unknownPublication")} role="alert">
            <Stack gap="sm">
              <Text size="sm">{flow.message ?? t("unknownDescription")}</Text>
              <Group>
                <Button
                  onClick={() => {
                    void props.onCheckOutcome();
                  }}
                  loading={flow.checking}
                >
                  {t("checkOutcome")}
                </Button>
                <Button
                  variant="default"
                  onClick={props.onCancel}
                  disabled={flow.checking}
                  loading={props.cancelling}
                >
                  {t("keepConnection")}
                </Button>
              </Group>
            </Stack>
          </Alert>
        )}
        {review != null && flow.type === "REVIEW" && (
          <section aria-labelledby="google-review-heading">
            <Stack gap="md">
              <Title id="google-review-heading" order={4} tabIndex={-1}>
                {t(
                  props.reviewDecision === "ACCOUNT"
                    ? "accountChanged"
                    : props.reviewDecision === "PARTIAL"
                      ? "partialTitle"
                      : "reviewTitle",
                )}
              </Title>
              {props.reviewDecision === "ACCOUNT" && saved.type === "READY" && (
                <Alert color="yellow">
                  <Text size="sm">{t("accountMismatch")}</Text>
                  <Text size="sm" className={classes.identity}>
                    {saved.detail.identity?.email ??
                      saved.detail.identity?.subject}
                    {" → "}
                    {review.identity.email ?? review.identity.subject}
                  </Text>
                </Alert>
              )}
              <Text fw={600} className={classes.identity}>
                {review.identity.email ?? review.identity.subject}
              </Text>
              {props.reviewDecision === "PARTIAL" && (
                <Alert color="yellow">{t("partialImpact")}</Alert>
              )}
              {!review.renewable && (
                <Alert color="yellow">{t("missingRenewal")}</Alert>
              )}
              <details>
                <summary>{t("permissionDetails")}</summary>
                <Stack gap="xs" mt="sm">
                  <PermissionResult review={review} props={props} />
                  <Text size="sm" fw={500}>
                    {t("grantedScopeDetails")}
                  </Text>
                  {review.granted_scopes?.map((scope) => (
                    <Code className={classes.code} key={scope}>
                      {scope}
                    </Code>
                  )) ?? <Text size="sm">{t("access.unknown")}</Text>}
                </Stack>
              </details>
              <Group justify="flex-end">
                <Button
                  variant="default"
                  onClick={props.onCancel}
                  loading={props.cancelling}
                >
                  {common("cancel")}
                </Button>
                <Button
                  leftSection={<IconRefresh size="1rem" />}
                  onClick={() => {
                    void props.onRetryAuthorization();
                  }}
                  loading={props.cancelling}
                >
                  {t("reauthenticate")}
                </Button>
              </Group>
            </Stack>
          </section>
        )}
        {editable && !props.recoveryOnly && (
          <>
            <Stack gap="sm">
              <Title order={4}>{t("servicesTitle")}</Title>
              {googleServiceSchema.options.map((service) => {
                const selected = props.services.includes(service),
                  groups = catalog.filter((group) => group.service === service),
                  chosen = groups.filter((group) =>
                    props.toolGroups.includes(group.group),
                  );
                return (
                  <div className={classes.service} key={service}>
                    <Group justify="space-between" wrap="nowrap">
                      <Switch
                        label={t(`services.${service}`)}
                        checked={selected}
                        disabled={busy}
                        onChange={(event) =>
                          props.onServiceChange(
                            service,
                            event.currentTarget.checked,
                          )
                        }
                      />
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {selected
                          ? chosen.length === 0
                            ? t("selectedGroups", { count: 0 })
                            : chosen
                                .map((group) => t(`groups.${group.group}`))
                                .join(" · ")
                          : t("off")}
                      </Text>
                    </Group>
                    <Group
                      gap="xs"
                      mt="sm"
                      role="group"
                      aria-label={`${t(`services.${service}`)} ${t("presetsTitle")}`}
                    >
                      {googleGroupPresets.map((preset) => (
                        <Button
                          size="xs"
                          variant="default"
                          key={preset}
                          disabled={busy || !selected}
                          onClick={() => props.onPresetChange(service, preset)}
                        >
                          {t(`presets.${preset}`)}
                        </Button>
                      ))}
                    </Group>
                    <details className={classes.permission}>
                      <summary>{t("configurePermissions")}</summary>
                      <Stack gap="sm">
                        {groups.map((group) => (
                          <Stack gap="xs" key={group.group}>
                            <Checkbox
                              label={t(`groups.${group.group}`)}
                              checked={props.toolGroups.includes(group.group)}
                              disabled={!selected || busy}
                              onChange={(event) =>
                                props.onGroupChange(
                                  group.group,
                                  event.currentTarget.checked,
                                )
                              }
                            />
                            <details>
                              <summary>
                                {t("groupTools", {
                                  count: group.operations.length,
                                })}
                              </summary>
                              <Stack gap="xs" mt="xs">
                                {group.operations.map((op) => (
                                  <Code className={classes.code} key={op}>
                                    {op}
                                  </Code>
                                ))}
                              </Stack>
                            </details>
                          </Stack>
                        ))}
                        {saved.type === "READY" && (
                          <>
                            <Text size="xs" c="dimmed">
                              {t("notLiveVerified")}
                            </Text>
                            {saved.detail.accesses
                              .filter((access) => access.service === service)
                              .map((access) => (
                                <Badge
                                  w="fit-content"
                                  key={access.service}
                                  color={
                                    access.status === "permitted"
                                      ? "green"
                                      : "yellow"
                                  }
                                >
                                  {t(`access.${access.status}`)}
                                </Badge>
                              ))}
                          </>
                        )}
                        {service === "drive" &&
                          saved.type === "READY" &&
                          saved.detail.services.includes("drive") && (
                            <>
                              <Text size="xs">{t("driveExtentTitle")}</Text>
                              {saved.detail.drive_access.whole_content_read && (
                                <Text size="xs">{t("driveWholeRead")}</Text>
                              )}
                              {saved.detail.drive_access
                                .whole_content_write && (
                                <Text size="xs">{t("driveWholeWrite")}</Text>
                              )}
                              {!saved.detail.drive_access.whole_content_write &&
                                saved.detail.drive_access.app_file_write && (
                                  <Text size="xs">{t("driveAppWrite")}</Text>
                                )}
                              {!saved.detail.drive_access.whole_content_read &&
                                saved.detail.drive_access.app_file_read && (
                                  <Text size="xs">{t("driveAppRead")}</Text>
                                )}
                              <Button
                                variant="default"
                                onClick={props.onOpenPicker}
                                disabled={
                                  !props.pickerAvailable ||
                                  props.picker.type === "OPEN"
                                }
                                loading={props.picker.type === "LOADING"}
                              >
                                {t("openPicker")}
                              </Button>
                              {(props.picker.type === "OPEN" ||
                                props.picker.type === "LOADING") && (
                                <Button
                                  variant="subtle"
                                  onClick={props.onClosePicker}
                                >
                                  {t("closePicker")}
                                </Button>
                              )}
                              {!props.pickerAvailable && (
                                <Text size="xs" c="dimmed">
                                  {t(
                                    preparation.type === "READY" &&
                                      preparation.detail.picker_status !==
                                        "configured_unverified"
                                      ? "pickerOperatorRequired"
                                      : "pickerRequiresGrant",
                                  )}
                                </Text>
                              )}
                              <div role="status">
                                {props.picker.type === "SELECTED" && (
                                  <Text size="sm">
                                    {t("pickerSelected", {
                                      count: props.picker.count,
                                    })}
                                  </Text>
                                )}
                                {props.picker.type === "CANCELLED" && (
                                  <Text size="sm">{t("pickerCancelled")}</Text>
                                )}
                                {props.picker.type === "ERROR" && (
                                  <Alert color="red">
                                    {props.picker.message}
                                  </Alert>
                                )}
                              </div>
                            </>
                          )}
                      </Stack>
                    </details>
                  </div>
                );
              })}
            </Stack>
            <details className={classes.advanced}>
              <summary>{t("advanced")}</summary>
              <Stack gap="md">
                <TextInput
                  label={t("name")}
                  placeholder="Google"
                  value={props.metadata.name}
                  maxLength={255}
                  onChange={(event) =>
                    props.onMetadataChange({ name: event.currentTarget.value })
                  }
                />
                <TextInput
                  label={t("slug")}
                  value={props.metadata.slug}
                  maxLength={100}
                  onChange={(event) =>
                    props.onMetadataChange({ slug: event.currentTarget.value })
                  }
                />
                <Textarea
                  label={t("description")}
                  value={props.metadata.description}
                  onChange={(event) =>
                    props.onMetadataChange({
                      description: event.currentTarget.value,
                    })
                  }
                />
                <Textarea
                  label={t("prompt")}
                  value={props.metadata.prompt}
                  onChange={(event) =>
                    props.onMetadataChange({
                      prompt: event.currentTarget.value,
                    })
                  }
                />
                <NumberInput
                  label={t("timeout")}
                  value={props.timeout}
                  min={1}
                  max={300}
                  onChange={(value) => {
                    if (typeof value === "number") {
                      props.onTimeoutChange(value);
                    }
                  }}
                />
                <Switch
                  label={t("enabled")}
                  checked={props.metadata.enabled}
                  onChange={(event) =>
                    props.onMetadataChange({
                      enabled: event.currentTarget.checked,
                    })
                  }
                />
                <Switch
                  label={t("alwaysExpose")}
                  checked={props.metadata.alwaysExposeTools}
                  onChange={(event) =>
                    props.onMetadataChange({
                      alwaysExposeTools: event.currentTarget.checked,
                    })
                  }
                />
              </Stack>
            </details>
            <Group justify="space-between" align="flex-start">
              <details>
                <summary>{t("help")}</summary>
                <Stack gap="sm" mt="sm">
                  <Text size="xs">{t("notLiveVerified")}</Text>
                  <Text size="xs">{t("riskDescription")}</Text>
                  <Text size="xs">{t("noReplay")}</Text>
                  <Button size="xs" variant="subtle" onClick={props.onRefresh}>
                    {t("reload")}
                  </Button>
                </Stack>
              </details>
              {saved.type === "READY" &&
                saved.detail.status !== "not_connected" &&
                !props.disconnectConfirmation && (
                  <Button
                    color="red"
                    variant="subtle"
                    size="xs"
                    onClick={props.onAskDisconnect}
                    disabled={busy}
                  >
                    {t("disconnect")}
                  </Button>
                )}
            </Group>
            {props.disconnectConfirmation && (
              <Alert color="red" title={t("disconnectTitle")}>
                <ToolkitDisconnectConfirmation
                  personal={props.ownership === "user"}
                  description={t("disconnectDescription")}
                  pending={props.disconnecting}
                  confirmLabel={t("disconnect")}
                  cancelLabel={t("keepConnection")}
                  onConfirm={props.onDisconnect}
                  onCancel={props.onDismissDisconnect}
                />
              </Alert>
            )}
            <Group className={classes.footer} justify="space-between">
              <Text size="xs" c="dimmed">
                {t(
                  props.reconnect
                    ? props.settingsDirty
                      ? "dirty"
                      : "clean"
                    : "connectHint",
                )}
              </Text>
              <Group gap="sm">
                <Button
                  variant="default"
                  onClick={props.onClose}
                  disabled={busy}
                >
                  {common(props.reconnect ? "cancel" : "cancel")}
                </Button>
                <Button
                  onClick={props.onApply}
                  loading={props.savingServices}
                  disabled={
                    busy ||
                    unavailable ||
                    (props.reconnect ? !props.settingsDirty : !selectable)
                  }
                >
                  {t(props.reconnect ? "apply" : "connect")}
                </Button>
              </Group>
            </Group>
          </>
        )}
        {editable && props.recoveryOnly && (
          <Button variant="default" onClick={props.onClose}>
            {common("cancel")}
          </Button>
        )}
      </Stack>
    </Container>
  );
}
