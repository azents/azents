import { Anchor, List, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import {
  getToolkitSetupGuide,
  toolkitSetupGuides,
} from "../toolkit-setup-guidance";
import classes from "./ToolkitSetup.module.css";
import type { ReactElement } from "react";

export function ToolkitPreparationGuide({
  toolkitType,
}: {
  toolkitType: string;
}): ReactElement {
  const t = useTranslations("toolkitSetup");
  const guide = getToolkitSetupGuide(toolkitType);
  const docs = guide === "other" ? null : toolkitSetupGuides[guide].docs;
  return (
    <Stack gap="sm" className={classes.guide}>
      <Text fw={500}>{t(`guides.${guide}.purpose`)}</Text>
      <div>
        <Text size="sm" fw={600}>
          {t("beforeYouStart")}
        </Text>
        <Text size="sm" mt="xs">
          {t(`guides.${guide}.prepare`)}
        </Text>
      </div>
      <details className={classes.disclosure}>
        <summary>{t("setupOrder")}</summary>
        <List type="ordered" size="sm" spacing="xs" mt="sm">
          <List.Item>{t(`guides.${guide}.configure`)}</List.Item>
          <List.Item>{t(`guides.${guide}.verify`)}</List.Item>
        </List>
      </details>
      {docs != null && (
        <Anchor href={docs} target="_blank" rel="noreferrer" size="sm">
          {t("officialGuide")}
        </Anchor>
      )}
      <details className={classes.disclosure}>
        <summary>{t("ifItFails")}</summary>
        <Text size="sm" mt="sm">
          {t(`guides.${guide}.recovery`)}
        </Text>
      </details>
    </Stack>
  );
}
