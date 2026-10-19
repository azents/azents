"use client";
import { useWindowEvent } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";
import { isRecord } from "@/shared/lib/unknown-value";
interface AuthorizationRequestBubbleProps {
  toolkitName: string;
  authorizationUrl: string;
  variant?: "card" | "compact";
  /** authorizationUrl event to absent when click time to authorization URL fetches.. */
  getAuthorizationUrl?: () => Promise<string | null>;
  /** auth complete when callback called */
  onAuthorized: () => void;
}

export interface AuthorizationRequestBubbleViewProps {
  toolkitName: AuthorizationRequestBubbleProps["toolkitName"];
  variant: "card" | "compact";
  t: ReturnType<typeof useTranslations<"chat.authorization">>;
  isOpening: boolean;
  handleClick: () => Promise<void>;
}
export function useAuthorizationRequestBubbleController({
  toolkitName,
  authorizationUrl,
  variant = "card",
  getAuthorizationUrl,
  onAuthorized,
}: AuthorizationRequestBubbleProps): AuthorizationRequestBubbleViewProps {
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
  useWindowEvent("message", (event: MessageEvent<unknown>): void => {
    if (event.origin !== window.location.origin) {
      return;
    }
    const data = event.data;
    if (!isRecord(data) || data.type !== "azents-oauth-callback") {
      return;
    }

    if (data.success === true) {
      onAuthorized();
    }
  });
  return { toolkitName, variant, t, isOpening, handleClick };
}
