import { Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import classes from "./ToolkitSetup.module.css";
import type { ReactElement } from "react";

/** Accept only nonsecret metadata. Config and credentials are deliberately not props. */
export function ToolkitSettingsReview({
  provider,
  name,
  ownership,
  enabled,
  alwaysExposeTools,
}: {
  provider: string;
  name: string;
  ownership: "workspace" | "agent" | "user";
  enabled: boolean;
  alwaysExposeTools: boolean;
}): ReactElement {
  const t = useTranslations("toolkitSetup");
  return (
    <Stack gap="sm" role="region" aria-label={t("summary")}>
      <Text fw={600} size="sm">
        {t("summary")}
      </Text>
      <dl className={classes.summary}>
        <dt>{t("provider")}</dt>
        <dd>{provider}</dd>
        <dt>{t("name")}</dt>
        <dd>{name.trim() || provider}</dd>
        <dt>{t("scope")}</dt>
        <dd>
          {t(
            ownership === "user"
              ? "personalScope"
              : ownership === "agent"
                ? "agentScope"
                : "workspaceScope",
          )}
        </dd>
        <dt>{t("availability")}</dt>
        <dd>{t(enabled ? "enabled" : "disabled")}</dd>
        <dt>{t("discovery")}</dt>
        <dd>{t(alwaysExposeTools ? "always" : "search")}</dd>
      </dl>
      <Text size="xs">{t("secretsOmitted")}</Text>
    </Stack>
  );
}
