import { Badge, Stack, Text, ThemeIcon, UnstyledButton } from "@mantine/core";
import { IconCheck, IconCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import classes from "./GitHubWizard.module.css";
import type { ReactNode } from "react";

export interface GitHubWizardChoiceProps {
  title: string;
  description: string;
  icon: ReactNode;
  selected: boolean;
  onSelect: () => void;
}
export function GitHubWizardChoice({
  title,
  description,
  icon,
  selected,
  onSelect,
}: GitHubWizardChoiceProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github.wizard");
  return (
    <UnstyledButton
      type="button"
      className={classes.choice}
      data-selected={selected || void 0}
      aria-pressed={selected}
      aria-label={title}
      onClick={onSelect}
    >
      <div className={classes.choiceHeader}>
        <ThemeIcon
          className={classes.choiceIcon}
          data-wizard-icon-slot
          variant="light"
          color={selected ? void 0 : "gray"}
          aria-hidden
        >
          {icon}
        </ThemeIcon>
        <ThemeIcon
          className={classes.choiceCheck}
          data-wizard-check-slot
          variant="transparent"
          color={selected ? void 0 : "gray"}
          aria-hidden
        >
          {selected ? <IconCheck size="1em" /> : <IconCircle size="1em" />}
        </ThemeIcon>
      </div>
      <Text
        className={classes.choiceTitle}
        data-wizard-choice-title
        fw={600}
        size="sm"
      >
        {title}
      </Text>
      <Stack gap="xs" className={classes.choiceBody}>
        <Text data-wizard-choice-description size="sm" c="dimmed">
          {description}
        </Text>
        <div className={classes.selectedSlot}>
          {selected && (
            <Badge tt="none" variant="filled" size="sm">
              {t("selected")}
            </Badge>
          )}
        </div>
      </Stack>
    </UnstyledButton>
  );
}
