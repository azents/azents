"use client";

import { useEffect } from "react";
import { isWindowMessageTarget } from "@/shared/lib/window-message-target";

export function useGitHubAppInstallResultController({
  installationId,
}: {
  installationId: string;
}): Record<string, never> {
  useEffect(() => {
    const opener: unknown = window.opener;
    if (isWindowMessageTarget(opener)) {
      opener.postMessage(
        {
          type: "azents-github-app-installed",
          installation_id: installationId,
        },
        window.location.origin,
      );
      const timer = setTimeout(() => window.close(), 1500);
      return () => clearTimeout(timer);
    }
    return () => {};
  }, [installationId]);
  return {};
}

export function useGitHubInstallationsCodeRelayController({
  code,
  state,
}: {
  code: string;
  state: string;
}): Record<string, never> {
  useEffect(() => {
    const opener: unknown = window.opener;
    if (isWindowMessageTarget(opener)) {
      opener.postMessage(
        { type: "azents-github-installations-code", code, state },
        window.location.origin,
      );
      const timer = setTimeout(() => window.close(), 1500);
      return () => clearTimeout(timer);
    }
    return () => {};
  }, [code, state]);
  return {};
}
