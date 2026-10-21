"use client";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { isWindowMessageTarget } from "@/shared/lib/window-message-target";
interface OAuthMcpCallbackResultProps {
  success: boolean;
  message: string | null;
  returnHref: string | null;
}

export interface OAuthMcpCallbackResultViewProps {
  success: OAuthMcpCallbackResultProps["success"];
  message: OAuthMcpCallbackResultProps["message"];
  returnHref: OAuthMcpCallbackResultProps["returnHref"];
  t: ReturnType<typeof useTranslations<"oauth">>;
}
export function useOAuthMcpCallbackResultController({
  success,
  message,
  returnHref,
}: OAuthMcpCallbackResultProps): OAuthMcpCallbackResultViewProps {
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
  return { success, message, returnHref, t };
}
