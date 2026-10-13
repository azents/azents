import { Text, Title } from "@mantine/core";
import classes from "./GitHubWizard.module.css";
import type { ReactNode } from "react";

export interface GitHubWizardSectionProps {
  id: string;
  number: number;
  title: string;
  subtitle?: string;
  complete?: boolean;
  disabled?: boolean;
  action?: ReactNode;
  children: ReactNode;
}
export function GitHubWizardSection({
  id,
  number,
  title,
  subtitle,
  complete = false,
  disabled = false,
  action,
  children,
}: GitHubWizardSectionProps): React.ReactElement {
  return (
    <section
      aria-labelledby={id}
      className={classes.section}
      data-complete={complete || void 0}
    >
      <div className={classes.sectionHeader}>
        <div className={classes.sectionHeadingRow}>
          <Title
            id={id}
            order={4}
            tabIndex={-1}
            className={classes.heading}
            data-wizard-section-title
          >
            {number}. {title}
          </Title>
          <div>{action}</div>
        </div>
        {subtitle != null && (
          <Text
            className={classes.sectionSubtitle}
            size="sm"
            c="dimmed"
            mt="xs"
          >
            {subtitle}
          </Text>
        )}
      </div>
      <fieldset
        disabled={disabled}
        className={classes.sectionBody}
        data-wizard-section-body
        aria-labelledby={id}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
      >
        {children}
      </fieldset>
    </section>
  );
}
