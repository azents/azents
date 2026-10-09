import {
  Alert,
  Anchor,
  Avatar,
  Button,
  Group,
  Modal,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { GitHubUserConnectionDetails } from "./GitHubUserConnectionDetails";
import type { GitHubUserSetupState } from "../types";
import type { GitHubUserConnectionDetailsProps } from "./GitHubUserConnectionDetails";
import type { GitHubUserConnectionSummary } from "@azents/public-client";

export interface GitHubUserAuthorizationProps extends GitHubUserConnectionDetailsProps {
  setup: GitHubUserSetupState;
  currentConnection: GitHubUserConnectionSummary | null;
  registrationDirty: boolean;
  onStart: () => void;
  onCancel: () => void;
  onConfirm: () => void;
  onCancelDisconnect: () => void;
  onDisconnect: () => void;
}
export function GitHubUserAuthorization(
  props: GitHubUserAuthorizationProps,
): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github.user");
  const reviewing =
    props.setup.type === "REVIEW" || props.setup.type === "CONFIRMING";
  const candidate =
    reviewing && "candidate" in props.setup ? props.setup.candidate : null;
  const pending = props.setup.type !== "IDLE" && props.setup.type !== "ERROR";
  const confirmBusy = props.setup.type === "CONFIRMING";
  return (
    <Stack gap="sm">
      <GitHubUserConnectionDetails {...props} />
      {props.registrationDirty && (
        <Alert color="yellow">{t("saveChangesFirst")}</Alert>
      )}
      {(props.setup.type === "IDLE" || props.setup.type === "ERROR") && (
        <Button
          variant="light"
          onClick={props.onStart}
          disabled={
            props.registrationDirty ||
            props.operation.type === "DISCONNECTING" ||
            (props.setup.type === "ERROR" && props.setup.attemptId != null)
          }
        >
          {t(props.currentConnection ? "reconnect" : "authorize")}
        </Button>
      )}
      {props.setup.type === "ERROR" && (
        <Alert color="red">
          <Stack gap="xs">
            <Text>{t(`errors.${props.setup.reason}`)}</Text>
            {props.setup.attemptId != null && (
              <Button variant="light" onClick={props.onCancel}>
                {t("cancelSetup")}
              </Button>
            )}
          </Stack>
        </Alert>
      )}
      {pending && !reviewing && (
        <Alert color="blue">
          <Stack gap="xs">
            <Text>
              {t(
                props.setup.type === "REVIEW_LOADING"
                  ? "loadingReview"
                  : props.setup.type === "CANCELLING"
                    ? "cancelling"
                    : "waiting",
              )}
            </Text>
            {props.setup.type === "WAITING" && (
              <Anchor
                href={props.setup.installUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("installApp")}
              </Anchor>
            )}
            <Button
              variant="subtle"
              onClick={props.onCancel}
              disabled={
                props.setup.type === "STARTING" ||
                props.setup.type === "CANCELLING"
              }
            >
              {t("cancelSetup")}
            </Button>
          </Stack>
        </Alert>
      )}
      <Modal
        opened={reviewing}
        onClose={props.onCancel}
        title={t("confirmTitle")}
        centered
        closeOnClickOutside={false}
        closeOnEscape={!confirmBusy}
        withCloseButton={!confirmBusy}
      >
        {candidate && (
          <Stack gap="md">
            <Group wrap="nowrap">
              <Avatar src={candidate.account_avatar_url} radius="xl" />
              <Text fw={600} style={{ overflowWrap: "anywhere" }}>
                {candidate.account_login}
              </Text>
            </Group>
            <Text>{t("confirmedAccountHint")}</Text>
            <Text>
              {t(
                candidate.sharing_scope === "workspace_shared"
                  ? "sharedScope"
                  : "agentScope",
              )}
            </Text>
            <Text size="sm">
              {t(candidate.source === "byoa_user" ? "byoa" : "platform")} ·{" "}
              {t("app", { id: candidate.app_id })}
            </Text>
            {props.currentConnection &&
              props.currentConnection.account_id !== candidate.account_id && (
                <Alert color="orange">
                  {t("replacementWarning", {
                    account: props.currentConnection.account_login,
                  })}
                </Alert>
              )}
            <Text size="sm" c="dimmed">
              {t("wrongAccountHint")}
            </Text>
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={props.onCancel}
                disabled={confirmBusy}
                data-autofocus
              >
                {t("cancelSetup")}
              </Button>
              <Button onClick={props.onConfirm} loading={confirmBusy}>
                {t("confirm")}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
      <Modal
        opened={
          props.operation.type === "DISCONNECT_CONFIRM" ||
          props.operation.type === "DISCONNECTING"
        }
        onClose={props.onCancelDisconnect}
        title={t("disconnectTitle")}
        centered
        closeOnClickOutside={false}
        closeOnEscape={props.operation.type !== "DISCONNECTING"}
        withCloseButton={props.operation.type !== "DISCONNECTING"}
      >
        <Stack>
          <Text>
            {t(
              props.sharingScope === "workspace_shared"
                ? "sharedDisconnectWarning"
                : "disconnectWarning",
            )}
          </Text>
          <Text size="sm" c="dimmed">
            {t("revocationLimit")}
          </Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              disabled={props.operation.type === "DISCONNECTING"}
              onClick={props.onCancelDisconnect}
              data-autofocus
            >
              {t("cancel")}
            </Button>
            <Button
              color="red"
              loading={props.operation.type === "DISCONNECTING"}
              onClick={props.onDisconnect}
            >
              {t("disconnect")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
