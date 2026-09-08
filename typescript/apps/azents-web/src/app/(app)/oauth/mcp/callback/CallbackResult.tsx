"use client";

/**
 * OAuth2 callback result client component.
 *
 * Receives token exchange result from server and sends to window.opener via postMessage,
 * then renders success/failure UI.
 */

import { Alert, Anchor, Stack, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

interface CallbackResultProps {
  success: boolean;
  message: string | null;
  returnHref?: string | null;
}

export function CallbackResult({
  success,
  message,
  returnHref = null,
}: CallbackResultProps): React.ReactElement {
  const t = useTranslations("oauth");

  useEffect(() => {
    const opener = window.opener as Window | null;
    if (opener) {
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
