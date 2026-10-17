"use client";

import { useInterval, useWindowEvent } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { isRecord } from "@/shared/lib/unknown-value";
import { trpc } from "@/trpc/client";
import { decodeGitHubPopupMessage } from "../popup-messages";
import { projectGitHubAuthEvidence } from "../provider-config-views";
import { pickToolkitOwnerScope } from "../toolkit-owner-scope";
import type { GithubFieldsViewProps } from "../components/GithubFieldsView";
import type { ToolkitOwnerScope } from "../toolkit-owner-scope";
import type { GithubInstallationState, InstallationTarget } from "../types";
import type { GitHubPlatformAuthorizationStateResponse } from "@azents/public-client";

export type GithubConfigFieldsProps = ToolkitOwnerScope & {
  config: Record<string, unknown>;
  onConfigChange: (config: Record<string, unknown>) => void;
  credentials: Record<string, unknown> | null;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  hasCredentials: boolean;
  authorizationState: GitHubPlatformAuthorizationStateResponse | null;
  savedAuthType?: string;
  toolkitConfigId?: string;
};
function targets(value: unknown): InstallationTarget[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) =>
    isRecord(item) &&
    typeof item.installation_id === "string" &&
    typeof item.account_login === "string" &&
    typeof item.account_type === "string"
      ? [
          {
            installation_id: item.installation_id,
            account_login: item.account_login,
            account_type: item.account_type,
            account_avatar_url:
              typeof item.account_avatar_url === "string"
                ? item.account_avatar_url
                : null,
          },
        ]
      : [],
  );
}

export function useGithubConfigFieldsContainer(
  props: GithubConfigFieldsProps,
): GithubFieldsViewProps {
  const t = useTranslations("workspace.toolkits.github");
  const utils = trpc.useUtils();
  const scope = pickToolkitOwnerScope(props);
  const availability = trpc.toolkit.githubUser.availability.useQuery(scope);
  const getInstallations = trpc.toolkit.getGithubInstallations.useMutation();
  const test = trpc.toolkit.testConnection.useMutation();
  const [runtimeAcknowledged, setRuntimeAcknowledged] = useState(false);
  const [installationState, setInstallationState] =
    useState<GithubInstallationState>({ type: "IDLE", installations: [] });
  const popup = useRef<Window | null>(null);
  const afterClose = useRef<(() => void) | null>(null);
  const { start, stop } = useInterval(() => {
    if (popup.current?.closed) {
      popup.current = null;
      stop();
      setInstallationState((current) => ({
        type: "IDLE",
        installations: current.installations,
      }));
      afterClose.current?.();
      afterClose.current = null;
    }
  }, 500);
  useEffect(
    () => () => {
      stop();
    },
    [stop],
  );
  function open(url: string, closed?: () => void): void {
    popup.current?.close();
    popup.current = window.open(
      url,
      "github-installation-popup",
      "width=1024,height=768",
    );
    afterClose.current = closed ?? null;
    if (popup.current) {
      start();
    } else {
      setInstallationState((current) => ({
        type: "ERROR",
        installations: current.installations,
      }));
    }
  }
  async function connectInstallations(): Promise<void> {
    setInstallationState((current) => ({
      type: "LOADING",
      installations: current.installations,
    }));
    try {
      const data = await utils.toolkit.getGithubOauthUrl.fetch(scope);
      open(data.oauth_url);
    } catch {
      setInstallationState((current) => ({
        type: "ERROR",
        installations: current.installations,
      }));
    }
  }
  useWindowEvent("message", (event: MessageEvent<unknown>): void => {
    const message = decodeGitHubPopupMessage(
      event,
      window.location.origin,
      popup.current,
      true,
    );
    if (message === null) {
      return;
    }
    if (message.type === "azents-github-installations-code") {
      popup.current = null;
      stop();
      setInstallationState((current) => ({
        type: "LOADING",
        installations: current.installations,
      }));
      void getInstallations
        .mutateAsync({
          ...scope,
          code: message.code,
          state: message.state,
        })
        .then((data) => {
          setInstallationState({
            type: "READY",
            installations: data.installations,
          });
        })
        .catch(() =>
          setInstallationState((current) => ({
            type: "ERROR",
            installations: current.installations,
          })),
        );
    } else {
      popup.current = null;
      stop();
      void connectInstallations();
    }
  });
  return {
    ...props,
    savedUserRegistration:
      props.hasCredentials && props.savedAuthType === "github_app_user",
    availability: availability.isError
      ? { type: "ERROR" }
      : availability.data
        ? { type: "READY", availability: availability.data }
        : { type: "LOADING" },
    selectedInstallations: targets(props.credentials?.installations),
    installationState,
    runtimeAcknowledged,
    canTest: ["pat", "github_app", "github_app_platform"].includes(
      projectGitHubAuthEvidence(props.config).savedDisplay,
    ),
    testState: test.isPending
      ? { type: "TESTING" }
      : test.data
        ? {
            type: "RESULT",
            success: test.data.success,
            message: test.data.success
              ? t("testConnectionSuccess")
              : t("testConnectionFailed", { message: test.data.message }),
          }
        : test.isError
          ? {
              type: "RESULT",
              success: false,
              message: t("testConnectionFailed", {
                message: test.error.message,
              }),
            }
          : { type: "IDLE" },
    onRetryAvailability: () => {
      void utils.toolkit.githubUser.availability.invalidate(scope);
    },
    onRuntimeAcknowledged: setRuntimeAcknowledged,
    onConnectInstallations: () => {
      void connectInstallations();
    },
    onInstallApp: () => {
      void utils.toolkit.getGithubInstallUrl
        .fetch(scope)
        .then((data) =>
          open(data.install_url, () => {
            void connectInstallations();
          }),
        )
        .catch(() =>
          setInstallationState((current) => ({
            type: "ERROR",
            installations: current.installations,
          })),
        );
    },
    onTest: () =>
      test.mutate({
        ...scope,
        toolkitType: "github",
        toolkitConfigId: props.toolkitConfigId ?? null,
        config: props.config,
        credentials: props.credentials,
      }),
  };
}
