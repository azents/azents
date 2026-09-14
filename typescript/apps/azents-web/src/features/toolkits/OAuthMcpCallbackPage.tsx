import { Container, Stack, Title } from "@mantine/core";
import { getTranslations } from "next-intl/server";
import { OAuthMcpCallbackResult } from "./components/OAuthMcpCallbackResult";

interface OAuthMcpCallbackPageProps {
  success: boolean;
  message: string | null;
  returnHref: string | null;
}

export async function OAuthMcpCallbackPage({
  success,
  message,
  returnHref,
}: OAuthMcpCallbackPageProps): Promise<React.ReactElement> {
  const t = await getTranslations("oauth");

  return (
    <Container size="xs" py="xl">
      <Stack align="center" gap="lg">
        <Title order={2}>{t("title")}</Title>
        <OAuthMcpCallbackResult
          success={success}
          message={message}
          returnHref={returnHref}
        />
      </Stack>
    </Container>
  );
}
