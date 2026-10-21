"use client";
import { Alert, Anchor, Stack, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";

/** Send the OAuth result to the opener and render the callback outcome. */

import { useOAuthMcpCallbackResultController } from "../containers/useOAuthMcpCallbackResultController";
import type { OAuthMcpCallbackResultViewProps } from "../containers/useOAuthMcpCallbackResultController";

interface OAuthMcpCallbackResultProps {
  success: boolean;
  message: string | null;
  returnHref: string | null;
}

export function OAuthMcpCallbackResult(
  props: OAuthMcpCallbackResultProps,
): React.ReactElement {
  return (
    <OAuthMcpCallbackResultView
      {...useOAuthMcpCallbackResultController(props)}
    />
  );
}

export function OAuthMcpCallbackResultView({
  success,
  message,
  returnHref,
  t,
}: OAuthMcpCallbackResultViewProps): React.ReactElement {
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
