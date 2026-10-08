import {
  Alert,
  Avatar,
  Button,
  Group,
  Loader,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type { GitHubUserSetupState } from "../github-user-oauth-state";

export interface GitHubUserCreationProps {
  state: GitHubUserSetupState;
  onCancel: () => void;
  onConfirm: () => void;
}
export function GitHubUserCreation({
  state,
  onCancel,
  onConfirm,
}: GitHubUserCreationProps): React.ReactElement | null {
  const t = useTranslations("workspace.toolkits.github.user");
  if (state.type === "IDLE") {
    return null;
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="red">
        <Stack>
          <Text>{t(`errors.${state.reason}`)}</Text>
          {state.attemptId != null && (
            <Button onClick={onCancel}>{t("cancelSetup")}</Button>
          )}
        </Stack>
      </Alert>
    );
  }
  if (state.type === "REVIEW" || state.type === "CONFIRMING") {
    const candidate = state.candidate;
    return (
      <Stack gap="md">
        <Text fw={600}>{t("confirmTitle")}</Text>
        <Group>
          <Avatar src={candidate.account_avatar_url} />
          <Text fw={600}>{candidate.account_login}</Text>
        </Group>
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
        <Text c="dimmed" size="sm">
          {t("wrongAccountHint")}
        </Text>
        <Group justify="flex-end">
          <Button
            variant="default"
            disabled={state.type === "CONFIRMING"}
            onClick={onCancel}
          >
            {t("cancelSetup")}
          </Button>
          <Button loading={state.type === "CONFIRMING"} onClick={onConfirm}>
            {t("confirm")}
          </Button>
        </Group>
      </Stack>
    );
  }
  return (
    <Stack>
      <Loader />
      <Text>
        {t(
          state.type === "REVIEW_LOADING"
            ? "loadingReview"
            : state.type === "CANCELLING"
              ? "cancelling"
              : "waiting",
        )}
      </Text>
    </Stack>
  );
}
