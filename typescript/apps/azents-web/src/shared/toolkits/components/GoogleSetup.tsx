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
import { useTranslations } from "next-intl";
import { googleTaskSchema } from "../google-schemas";
import type { GoogleSetupProps } from "../google-types";
import type { GoogleTaskAccess } from "@azents/public-client";

function Capability({
  access,
}: {
  access: GoogleTaskAccess;
}): React.ReactElement {
  const t = useTranslations("googleToolkit");
  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="wrap">
        <Text fw={500}>{t(`tasks.${access.task}.title`)}</Text>
        <Badge
          color={
            access.status === "permitted"
              ? "green"
              : access.status === "partial"
                ? "yellow"
                : "gray"
          }
        >
          {t(`access.${access.status}`)}
        </Badge>
      </Group>
      <Text size="sm" c="dimmed">
        {t(`tasks.${access.task}.description`)}
      </Text>
      <Text size="xs">
        {t("availableActions", { count: access.permitted_tools.length })}
      </Text>
      <details>
        <summary>{t("permissionDetails")}</summary>
        <Stack gap="xs" mt="sm">
          <Text size="xs" fw={600}>
            {t("permittedTools")}
          </Text>
          {access.permitted_tools.map((name) => (
            <Code key={name} style={{ overflowWrap: "anywhere" }}>
              {name}
            </Code>
          ))}
          <Text size="xs" fw={600}>
            {t("unavailableTools")}
          </Text>
          {access.unavailable_tools.map((name) => (
            <Code key={name} style={{ overflowWrap: "anywhere" }}>
              {name}
            </Code>
          ))}
        </Stack>
      </details>
    </Stack>
  );
}
export function GoogleSetup(props: GoogleSetupProps): React.ReactElement {
  const t = useTranslations("googleToolkit");
  const { preparation, saved, flow } = props;
  const review =
    flow.type === "REVIEW" || flow.type === "CONFIRMING" ? flow.review : null;
  const busy =
    flow.type === "AUTHORIZING" ||
    flow.type === "VERIFYING" ||
    flow.type === "CONFIRMING" ||
    props.cancelling ||
    props.disconnecting;
  const selecting = flow.type === "SELECT";
  return (
    <Container
      size="md"
      w="100%"
      miw={0}
      py={props.embedded ? 0 : "lg"}
      px={props.embedded ? 0 : "md"}
    >
      <Stack gap="lg" ref={props.rootRef}>
        <Title order={3}>
          {props.reconnect ? t("reconnectTitle") : t("title")}
        </Title>
        <Text size="sm" c="dimmed">
          {t("intro")}
        </Text>
        {props.operationError != null && (
          <Alert color="red" role="alert">
            {props.operationError}
          </Alert>
        )}
        {saved.type === "LOADING" && <Loader size="sm" />}
        {saved.type === "ERROR" && (
          <Alert color="red" role="alert">
            {saved.message}
            <Button type="button" variant="subtle" onClick={props.onRefresh}>
              {t("reload")}
            </Button>
          </Alert>
        )}
        {saved.type === "READY" && (
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={600}>{t("savedAccount")}</Text>
              <Badge>{t(`connection.${saved.detail.status}`)}</Badge>
            </Group>
            {saved.detail.identity != null && (
              <Text style={{ overflowWrap: "anywhere" }}>
                {saved.detail.identity.email ?? saved.detail.identity.subject}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              {t("notLiveVerified")}
            </Text>
            {saved.detail.tasks.map((access) => (
              <Capability key={access.task} access={access} />
            ))}
            {!props.disconnectConfirmation &&
              saved.detail.status !== "not_connected" && (
                <Button
                  type="button"
                  color="red"
                  variant="subtle"
                  disabled={busy || flow.type === "UNKNOWN"}
                  onClick={props.onAskDisconnect}
                >
                  {t("disconnect")}
                </Button>
              )}
            {props.disconnectConfirmation && (
              <Alert color="red" title={t("disconnectTitle")}>
                <Text size="sm">{t("disconnectDescription")}</Text>
                <Group mt="sm">
                  <Button
                    type="button"
                    color="red"
                    loading={props.disconnecting}
                    onClick={props.onDisconnect}
                  >
                    {t("disconnect")}
                  </Button>
                  <Button
                    type="button"
                    variant="default"
                    disabled={props.disconnecting}
                    onClick={props.onDismissDisconnect}
                  >
                    {t("keepConnection")}
                  </Button>
                </Group>
              </Alert>
            )}
          </Stack>
        )}
        <Divider />
        {preparation.type === "LOADING" ? (
          <Loader size="sm" />
        ) : preparation.type === "ERROR" ? (
          <Alert color="red" role="alert">
            {preparation.message}
            <Button type="button" onClick={props.onRefresh}>
              {t("reload")}
            </Button>
          </Alert>
        ) : preparation.detail.status !== "configured_unverified" ? (
          <Alert color="yellow" title={t("operatorRequired")}>
            <Text size="sm">{t("operatorDescription")}</Text>
            <Button type="button" variant="subtle" onClick={props.onRefresh}>
              {t("reload")}
            </Button>
          </Alert>
        ) : (
          <Text size="xs" c="dimmed">
            {t("preparationUnverified")}
          </Text>
        )}
        <section aria-labelledby="google-select-heading">
          <Stack gap="md">
            <Title order={4} id="google-select-heading" tabIndex={-1}>
              {t("selectTasks")}
            </Title>
            <details open={selecting}>
              <summary>{t("selectionDetails")}</summary>
              <Stack gap="md" mt="sm">
                <Text size="sm">{t("selectDescription")}</Text>
                {googleTaskSchema.options.map((task) => (
                  <Checkbox
                    key={task}
                    label={t(`tasks.${task}.title`)}
                    description={t(`tasks.${task}.description`)}
                    checked={props.tasks.includes(task)}
                    disabled={!selecting}
                    onChange={(event) =>
                      props.onTaskChange(task, event.currentTarget.checked)
                    }
                  />
                ))}
                <NumberInput
                  label={t("timeout")}
                  value={props.timeout}
                  min={1}
                  max={300}
                  disabled={!selecting}
                  onChange={(value) => {
                    if (typeof value === "number") {
                      props.onTimeoutChange(value);
                    }
                  }}
                />
              </Stack>
            </details>
            {selecting && (
              <Button
                type="button"
                onClick={props.onAuthorize}
                disabled={
                  props.tasks.length === 0 ||
                  preparation.type !== "READY" ||
                  preparation.detail.status !== "configured_unverified" ||
                  saved.type === "LOADING" ||
                  saved.type === "ERROR"
                }
              >
                {props.reconnect ? t("authorizeAgain") : t("authorize")}
              </Button>
            )}
          </Stack>
        </section>
        {(flow.type === "AUTHORIZING" || flow.type === "VERIFYING") && (
          <Group role="status">
            <Loader size="sm" />
            <Text>
              {flow.type === "AUTHORIZING" ? t("authorizing") : t("verifying")}
            </Text>
          </Group>
        )}
        {flow.type === "ERROR" && (
          <Alert role="alert" color="red" title={t("failed")}>
            <Text>{flow.message}</Text>
            <Button mt="sm" type="button" onClick={props.onRestart}>
              {t("restart")}
            </Button>
          </Alert>
        )}
        {review != null && (
          <section aria-labelledby="google-review-heading">
            <Stack gap="md">
              <Title order={4} id="google-review-heading" tabIndex={-1}>
                {t("reviewTitle")}
              </Title>
              <Text fw={600} style={{ overflowWrap: "anywhere" }}>
                {review.identity.email ?? review.identity.subject}
              </Text>
              <Text size="sm" c="dimmed">
                {props.agentOwned ? t("agentOwnership") : t("sharedOwnership")}
              </Text>
              <Alert
                color={review.grant_result === "full" ? "blue" : "yellow"}
                title={t(`grant.${review.grant_result}`)}
              >
                <Text size="sm">{t("actualPermissions")}</Text>
                {!review.renewable && (
                  <Text size="sm" mt="xs">
                    {t("missingRenewal")}
                  </Text>
                )}
              </Alert>
              {review.tasks.map((access) => (
                <Stack key={access.task} gap="xs">
                  <Capability access={access} />
                  <Checkbox
                    label={t("includeTask")}
                    checked={props.tasks.includes(access.task)}
                    disabled={busy}
                    onChange={(event) =>
                      props.onTaskChange(
                        access.task,
                        event.currentTarget.checked,
                      )
                    }
                  />
                </Stack>
              ))}
              <Text size="xs" c="dimmed">
                {t("notLiveVerified")}
              </Text>
              {!props.reconnect && (
                <>
                  <Divider />
                  <TextInput
                    label={t("name")}
                    placeholder="Google"
                    value={props.metadata.name}
                    disabled={busy}
                    onChange={(event) =>
                      props.onMetadataChange({
                        name: event.currentTarget.value,
                      })
                    }
                  />
                  <TextInput
                    label={t("slug")}
                    value={props.metadata.slug}
                    disabled={busy}
                    onChange={(event) =>
                      props.onMetadataChange({
                        slug: event.currentTarget.value,
                      })
                    }
                  />
                  <Textarea
                    label={t("description")}
                    value={props.metadata.description}
                    disabled={busy}
                    onChange={(event) =>
                      props.onMetadataChange({
                        description: event.currentTarget.value,
                      })
                    }
                  />
                  <Textarea
                    label={t("prompt")}
                    value={props.metadata.prompt}
                    disabled={busy}
                    onChange={(event) =>
                      props.onMetadataChange({
                        prompt: event.currentTarget.value,
                      })
                    }
                  />
                  <Switch
                    label={t("enabled")}
                    checked={props.metadata.enabled}
                    disabled={busy}
                    onChange={(event) =>
                      props.onMetadataChange({
                        enabled: event.currentTarget.checked,
                      })
                    }
                  />
                  <Switch
                    label={t("alwaysExpose")}
                    checked={props.metadata.alwaysExposeTools}
                    disabled={busy}
                    onChange={(event) =>
                      props.onMetadataChange({
                        alwaysExposeTools: event.currentTarget.checked,
                      })
                    }
                  />
                </>
              )}
              <Alert color="yellow" title={t("riskTitle")}>
                <Text size="sm">{t("riskDescription")}</Text>
                <Text size="sm" mt="xs">
                  {t("noReplay")}
                </Text>
              </Alert>
              <Checkbox
                label={t("acknowledge")}
                checked={props.acknowledged}
                disabled={busy}
                onChange={(event) =>
                  props.onAcknowledgedChange(event.currentTarget.checked)
                }
              />
              <Group>
                <Button
                  type="button"
                  onClick={props.onPublish}
                  loading={flow.type === "CONFIRMING"}
                  disabled={!props.publishingAllowed || props.cancelling}
                >
                  {props.reconnect ? t("replace") : t("save")}
                </Button>
                <Button
                  type="button"
                  variant="default"
                  onClick={props.onCancel}
                  disabled={busy}
                  loading={props.cancelling}
                >
                  {t("cancel")}
                </Button>
              </Group>
            </Stack>
          </section>
        )}
        {flow.type === "UNKNOWN" && (
          <Alert color="yellow" title={t("unknownPublication")}>
            <Text>{t("unknownDescription")}</Text>
            {flow.message != null && (
              <Text size="sm" mt="xs">
                {flow.message}
              </Text>
            )}
            <Group mt="sm">
              <Button
                type="button"
                onClick={props.onCheckOutcome}
                loading={flow.checking}
                disabled={props.cancelling}
              >
                {t("checkOutcome")}
              </Button>
              <Button
                type="button"
                variant="default"
                onClick={props.onCancel}
                disabled={flow.checking}
                loading={props.cancelling}
              >
                {t("cancel")}
              </Button>
            </Group>
          </Alert>
        )}
        {flow.type === "COMPLETE" && (
          <Alert
            color={flow.outcome.current ? "green" : "yellow"}
            title={flow.outcome.current ? t("saved") : t("superseded")}
          >
            <Text size="sm">
              {flow.outcome.current
                ? t("savedDescription")
                : t("supersededDescription")}
            </Text>
            {props.reconnect && (
              <Button
                type="button"
                variant="subtle"
                mt="sm"
                onClick={props.onRestart}
              >
                {t("reconnectTitle")}
              </Button>
            )}
          </Alert>
        )}
        {flow.type !== "UNKNOWN" &&
          flow.type !== "COMPLETE" &&
          review == null &&
          flow.type !== "SELECT" && (
            <Button
              type="button"
              variant="default"
              disabled={busy}
              loading={props.cancelling}
              onClick={props.onCancel}
            >
              {t("cancel")}
            </Button>
          )}
      </Stack>
    </Container>
  );
}
