"use client";

/**
 * OAuth2 per-user authorization request card.
 *
 * toolkit user auth required with to when chat to is shown..
 * authorization URL new tab in can open button includes..
 */

import { Alert, Button, Group, Text } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

interface AuthorizationRequestBubbleProps {
  toolkitName: string;
  authorizationUrl: string;
  /** authorizationUrl event to absent when click time to authorization URL fetches.. */
  getAuthorizationUrl?: () => Promise<string | null>;
  /** auth complete when callback called */
  onAuthorized: () => void;
}

export function AuthorizationRequestBubble({
  toolkitName,
  authorizationUrl,
  getAuthorizationUrl,
  onAuthorized,
}: AuthorizationRequestBubbleProps): React.ReactElement {
  const t = useTranslations("chat.authorization");
  const popupRef = useRef<Window | null>(null);
  const [isOpening, setIsOpening] = useState(false);

  /** OAuth open popup */
  const handleClick = useCallback(async () => {
    setIsOpening(true);

    // Open popup before async URL fetch to avoid popup blocker.
    const popup = window.open(
      "about:blank",
      "azents-oauth",
      "width=600,height=700,popup=yes",
    );
    popupRef.current = popup;

    try {
      const resolvedUrl = authorizationUrl || (await getAuthorizationUrl?.());
      if (!resolvedUrl) {
        popup?.close();
        return;
      }

      if (popup && !popup.closed) {
        popup.location.href = resolvedUrl;
      } else {
        window.open(resolvedUrl, "_blank", "noopener,noreferrer");
      }
    } catch {
      popup?.close();
    } finally {
      setIsOpening(false);
    }
  }, [authorizationUrl, getAuthorizationUrl]);

  /** postMessage handler: OAuth receive result from callback popup */
  useEffect(() => {
    const handleMessage = (event: MessageEvent<unknown>): void => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const data = event.data;
      if (
        typeof data !== "object" ||
        data === null ||
        !("type" in data) ||
        (data as { type: string }).type !== "azents-oauth-callback"
      ) {
        return;
      }

      if (
        "success" in data &&
        (data as { success: unknown }).success === true
      ) {
        onAuthorized();
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onAuthorized]);

  return (
    <Group
      align="flex-start"
      gap="sm"
      justify="flex-start"
      wrap="nowrap"
      mb="md"
    >
      <Alert
        icon={<IconLock size={18} />}
        title={t("authorizationRequired")}
        color="yellow"
        variant="light"
        maw="100%"
      >
        <Text size="sm" mb="sm">
          {t("authorizationRequestMessage", { toolkitName })}
        </Text>
        <Button
          size="sm"
          variant="filled"
          onClick={() => void handleClick()}
          loading={isOpening}
        >
          {t("authorizeButton")}
        </Button>
      </Alert>
    </Group>
  );
}
