import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type {
  GitHubUserAccessState,
  GitHubUserOperationState,
  GitHubUserStatusState,
} from "../github-user-oauth-state";

export interface GitHubUserConnectionDetailsProps {
  status: GitHubUserStatusState;
  access: GitHubUserAccessState;
  operation: GitHubUserOperationState;
  sharingScope: "workspace_shared" | "agent_only";
  onRetryStatus: () => void;
  onRequestDisconnect: () => void;
  onRecheckAccess: () => void;
  onMoreAccess: () => void;
}
export function GitHubUserConnectionDetails(
  props: GitHubUserConnectionDetailsProps,
): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github.user");
  if (props.status.type === "LOADING") {
    return <Loader size="sm" role="status" aria-label={t("statusLoading")} />;
  }
  if (props.status.type === "ERROR") {
    return (
      <Alert color="red">
        <Stack gap="xs">
          <Text>{t("statusError")}</Text>
          <Button variant="light" onClick={props.onRetryStatus}>
            {t("retry")}
          </Button>
        </Stack>
      </Alert>
    );
  }
  const { connection } = props.status;
  const owners =
    "installations" in props.access ? props.access.installations : [];
  const busy = props.operation.type === "DISCONNECTING";
  function permission(value: boolean | null): string {
    return value == null ? t("unknown") : value ? t("yes") : t("no");
  }
  return (
    <Stack gap="sm">
      {connection ? (
        <>
          <Text fw={600} style={{ overflowWrap: "anywhere" }}>
            {t("executionAccount", { account: connection.account_login })}
          </Text>
          <Group>
            <Badge>
              {t(connection.source === "byoa_user" ? "byoa" : "platform")}
            </Badge>
            <Text size="sm">{t("app", { id: connection.app_id })}</Text>
            <Badge
              color={connection.status === "connected" ? "green" : "yellow"}
            >
              {t(
                connection.status === "connected"
                  ? "connected"
                  : "reconnectRequired",
              )}
            </Badge>
          </Group>
          {connection.status === "reconnect_required" && (
            <Alert color="yellow">{t("reconnectExplanation")}</Alert>
          )}
        </>
      ) : (
        <Stack gap="xs">
          <Text size="sm">{t("notConnected")}</Text>
          <Text size="xs" c="dimmed">
            {t("localDisconnectionHint")}
          </Text>
        </Stack>
      )}
      <Text size="sm">
        {t(
          props.sharingScope === "workspace_shared"
            ? "sharedScope"
            : "agentScope",
        )}
      </Text>
      {props.operation.type === "ERROR" && (
        <Alert color="red">{t(`errors.${props.operation.reason}`)}</Alert>
      )}
      {connection && (
        <Button
          variant="subtle"
          color="red"
          onClick={props.onRequestDisconnect}
          loading={props.operation.type === "DISCONNECTING"}
          disabled={busy}
        >
          {t("disconnect")}
        </Button>
      )}
      {connection?.status === "connected" && (
        <>
          <Text size="sm" fw={600}>
            {t("accessTitle")}
          </Text>
          <Text size="xs" c="dimmed">
            {t("accessHint")}
          </Text>
          <Group>
            <Button
              variant="light"
              onClick={props.onRecheckAccess}
              loading={props.access.type === "LOADING"}
              disabled={props.access.type === "MORE"}
            >
              {t("recheck")}
            </Button>
            <Anchor
              href="https://github.com/settings/installations"
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("manageAccess")}
            </Anchor>
          </Group>
          {props.access.type === "IDLE" && (
            <Text size="sm" c="dimmed">
              {t("accessUnknown")}
            </Text>
          )}
          {props.access.type === "ERROR" && (
            <Alert color="yellow">{t("accessError")}</Alert>
          )}
          {props.access.type === "READY" && owners.length === 0 && (
            <Text size="sm">{t("noOwners")}</Text>
          )}
          {owners.map((owner) => (
            <Stack key={owner.installation_id} gap="xs" style={{ minWidth: 0 }}>
              <Group>
                <Text fw={600} style={{ overflowWrap: "anywhere" }}>
                  {owner.account_login}
                </Text>
                <Badge variant="light">
                  {t(
                    owner.account_type === "User" ? "personal" : "organization",
                  )}
                </Badge>
                <Badge
                  color={
                    owner.repositories_complete && owner.failure_reason == null
                      ? "green"
                      : "yellow"
                  }
                >
                  {t(
                    owner.repositories_complete && owner.failure_reason == null
                      ? "observed"
                      : "partial",
                  )}
                </Badge>
              </Group>
              {owner.failure_reason != null && (
                <Text size="sm">
                  {t(
                    owner.failure_reason === "target_denied"
                      ? "targetDenied"
                      : "ownerUnavailable",
                  )}
                </Text>
              )}
              <Text size="xs" c="dimmed">
                {t("appPermissions")}:{" "}
                {Object.entries(owner.app_permissions)
                  .map(([name, value]) => `${name}: ${value}`)
                  .join(", ") || t("unknown")}
              </Text>
              {owner.repositories.map((repo) => (
                <Stack key={repo.repository_id} gap={0}>
                  <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                    {repo.full_name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t("repoPermissions", {
                      read: permission(repo.permissions.read),
                      write: permission(repo.permissions.write),
                      admin: permission(repo.permissions.admin),
                    })}
                  </Text>
                </Stack>
              ))}
              {!owner.repositories_complete && (
                <Text size="xs" c="dimmed">
                  {t("ownerIncomplete")}
                </Text>
              )}
            </Stack>
          ))}
          {"nextCursor" in props.access && props.access.nextCursor != null && (
            <Button
              variant="light"
              onClick={props.onMoreAccess}
              loading={props.access.type === "MORE"}
            >
              {t("loadMore")}
            </Button>
          )}
        </>
      )}
    </Stack>
  );
}
