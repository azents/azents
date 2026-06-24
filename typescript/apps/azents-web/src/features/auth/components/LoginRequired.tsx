"use client";

/**
 * Login required page component
 *
 * Rendered when server-side auth check determines unauthenticated.
 * Provides login link containing current path in next query param.
 */
import { Button, Stack, Text, Title } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { FormPageLayout } from "@/shared/components/FormPageLayout";

export function LoginRequired(): React.ReactElement {
  const t = useTranslations("auth");
  const pathname = usePathname();
  const searchParams = useSearchParams();

  /** Current full path (including query params) */
  const currentPath = searchParams.toString()
    ? `${pathname}?${searchParams.toString()}`
    : pathname;

  const loginUrl = `/login?next=${encodeURIComponent(currentPath)}`;

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
