"use client";

import { Box, Container, Group, Text } from "@mantine/core";
import { useTranslations } from "next-intl";

export function PageFooter(): React.ReactElement {
  const t = useTranslations("footer");

  return (
    <Box
      component="footer"
      py="xl"
      style={{
        borderTop: "1px solid rgba(154, 170, 188, 0.12)",
      }}
    >
      <Container size="xl">
        <Group justify="space-between">
          <Text c="dimmed" size="sm">
            {t("tagline")}
          </Text>
        </Group>
      </Container>
    </Box>
  );
}
