/**
 * Protected provider identity OAuth entry route.
 *
 * The account page and native provider surfaces can navigate here without
 * carrying OAuth state themselves; the server starts the authenticated attempt
 * and redirects to the fixed provider authorization URL.
 */

import { Container, Stack, Title } from "@mantine/core";
import { TRPCError } from "@trpc/server";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { trpc } from "@/trpc/server";
import { CallbackResult } from "../../../../oauth/mcp/callback/CallbackResult";

type Provider = "slack" | "discord";

interface PageProps {
  params: Promise<{ provider: string }>;
}

function parseProvider(value: string): Provider | null {
  return value === "slack" || value === "discord" ? value : null;
}

export default async function ExternalAccountConnectPage({
  params,
}: PageProps): Promise<React.ReactElement> {
  const t = await getTranslations("oauth");
  const { provider: providerParam } = await params;
  const provider = parseProvider(providerParam);

  if (provider === null) {
    return (
      <Container size="xs" py="xl">
        <Stack align="center" gap="lg">
          <Title order={2}>{t("title")}</Title>
          <CallbackResult
            success={false}
            message="Unsupported provider. Restart account connection."
            returnHref="/account/external-accounts"
          />
        </Stack>
      </Container>
    );
  }

  try {
    const result = await trpc.accountLinks.startOauth({ provider });
    redirect(result.authorization_url);
  } catch (error) {
    if (!(error instanceof TRPCError)) {
      throw error;
    }
    return (
      <Container size="xs" py="xl">
        <Stack align="center" gap="lg">
          <Title order={2}>{t("title")}</Title>
          <CallbackResult
            success={false}
            message={error.message}
            returnHref="/account/external-accounts"
          />
        </Stack>
      </Container>
    );
  }
}
