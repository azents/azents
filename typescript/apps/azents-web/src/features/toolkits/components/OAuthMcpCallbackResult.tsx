"use client";

/** Send the OAuth result to the opener and render the callback outcome. */

import { Alert, Anchor, Stack, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { isWindowMessageTarget } from "@/shared/lib/window-message-target";

interface OAuthMcpCallbackResultProps {
  success: boolean;
  message: string | null;
  returnHref: string | null;
}

export function OAuthMcpCallbackResult({
  success,
  message,
  returnHref,
}: OAuthMcpCallbackResultProps): React.ReactElement {
  const t = useTranslations("oauth");

  useEffect(() => {
    const opener: unknown = window.opener;
    if (isWindowMessageTarget(opener)) {
      opener.postMessage(
        { type: "azents-oauth-callback", success },
        window.location.origin,
      );
    }
  }, [success]);

  if (success) {
    return (
      <Stack align="center">
        <Alert icon={<IconCheck size={24} />} color="green" variant="light">
          <Text>{t("callbackSuccess")}</Text>
        </Alert>
        {returnHref && (
          <Anchor href={returnHref}>{t("returnToAgentSettings")}</Anchor>
        )}
      </Stack>
    );
  }

  return (
    <Stack align="center">
      <Alert icon={<IconX size={24} />} color="red" variant="light">
        <Text>{t("callbackError")}</Text>
        {message && (
          <Text size="sm" c="dimmed" mt="xs">
            {message}
          </Text>
        )}
      </Alert>
      {returnHref && (
        <Anchor href={returnHref}>{t("returnToAgentSettings")}</Anchor>
      )}
    </Stack>
  );
}
