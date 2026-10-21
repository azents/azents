"use client";

import { Button, Stack, Text, Title } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import Link from "next/link";
/**
 * Login required page component
 *
 * Rendered when server-side auth check determines unauthenticated.
 * Provides login link containing current path in next query param.
 */
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import { useLoginRequiredController } from "../containers/useLoginRequiredController";
import type { LoginRequiredViewProps } from "../containers/useLoginRequiredController";

export function LoginRequired(): React.ReactElement {
  return <LoginRequiredView {...useLoginRequiredController()} />;
}

export function LoginRequiredView({
  t,
  loginUrl,
}: LoginRequiredViewProps): React.ReactElement {
  return (
    <FormPageLayout>
      <Stack gap="lg" align="center">
        <IconLock size={48} stroke={1.5} style={{ opacity: 0.3 }} />

        <Stack gap="xs" align="center">
          <Title order={2}>{t("loginRequired.headline")}</Title>
          <Text c="dimmed" ta="center">
            {t("loginRequired.description")}
          </Text>
        </Stack>

        <Button component={Link} href={loginUrl} size="lg" fullWidth>
          {t("loginRequired.action")}
        </Button>
      </Stack>
    </FormPageLayout>
  );
}
