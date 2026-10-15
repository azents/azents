import { Stack, Text, Title } from "@mantine/core";
import { useId } from "react";
import classes from "./ToolkitSetup.module.css";
import type { ReactElement, ReactNode } from "react";

/** Numbering describes setup order, never verification or publication state. */
export function ToolkitSetupSection({
  number,
  title,
  description,
  children,
}: {
  number: number;
  title: string;
  description: string;
  children: ReactNode;
}): ReactElement {
  const id = useId();
  return (
    <section aria-labelledby={id} className={classes.section}>
      <div className={classes.header}>
        <Title order={4} id={id}>
          {number}. {title}
        </Title>
        <Text size="sm" mt="xs">
          {description}
        </Text>
      </div>
      <Stack gap="md">{children}</Stack>
    </section>
  );
}
