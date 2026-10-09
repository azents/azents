import { Alert, Anchor, Loader, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { GitHubUserOAuthCallbackState } from "../../../shared/toolkits/types";

export interface GitHubUserOAuthCallbackResultProps {
  state: GitHubUserOAuthCallbackState;
  returnPath: string | null;
}
export function GitHubUserOAuthCallbackResult({
  state,
  returnPath,
}: GitHubUserOAuthCallbackResultProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github.user");
  return (
    <Stack gap="md">
      {state.type === "LOADING" ? (
        <>
          <Loader size="sm" />
          <Text>{t("callbackLoading")}</Text>
        </>
      ) : (
        <Alert color={state.type === "COMPLETE" ? "blue" : "red"}>
          {state.type === "COMPLETE"
            ? t("callbackReview")
            : t(`errors.${state.reason}`)}
        </Alert>
      )}
      {returnPath && (
        <Anchor component={Link} href={returnPath}>
          {t("return")}
        </Anchor>
      )}
    </Stack>
  );
}
