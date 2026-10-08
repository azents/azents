"use client";
import { useInterval, useWindowEvent } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { isRecord } from "@/shared/lib/unknown-value";
import { trpc } from "@/trpc/client";
import type {
  GithubFieldsViewProps,
  InstallationItem,
  InstallationTarget,
} from "../components/GithubFieldsView";
import type { GitHubPlatformAuthorizationStateResponse } from "@azents/public-client";

export interface GithubConfigFieldsProps {
  config: Record<string, unknown>;
  onConfigChange: (config: Record<string, unknown>) => void;
  credentials: Record<string, unknown> | null;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  hasCredentials: boolean;
  authorizationState: GitHubPlatformAuthorizationStateResponse | null;
  savedAuthType?: string;
  handle?: string;
  agentId?: string;
  toolkitConfigId?: string;
}
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
  const availability = trpc.toolkit.githubUser.availability.useQuery(
    { handle: props.handle ?? "", agentId: props.agentId },
    { enabled: Boolean(props.handle) },
  );
  const getInstallations = trpc.toolkit.getGithubInstallations.useMutation();
  const test = trpc.toolkit.testConnection.useMutation();
  const [runtimeAcknowledged, setRuntimeAcknowledged] = useState(false);
  const [installations, setInstallations] = useState<InstallationItem[]>([]);
  const [installationState, setInstallationState] =
    useState<GithubFieldsViewProps["installationState"]>("IDLE");
  const popup = useRef<Window | null>(null);
  const afterClose = useRef<(() => void) | null>(null);
  const { start, stop } = useInterval(() => {
    if (popup.current?.closed) {
      popup.current = null;
      stop();
      setInstallationState("IDLE");
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
      setInstallationState("ERROR");
    }
  }
  async function connectInstallations(): Promise<void> {
    setInstallationState("LOADING");
    try {
      const data = await utils.toolkit.getGithubOauthUrl.fetch({
        handle: props.handle ?? "",
        agentId: props.agentId,
      });
      open(data.oauth_url);
    } catch {
      setInstallationState("ERROR");
    }
  }
  useWindowEvent("message", (event: MessageEvent<unknown>): void => {
    if (
      popup.current == null ||
      event.origin !== window.location.origin ||
      event.source !== popup.current ||
      !isRecord(event.data)
    ) {
      return;
    }
    if (
      event.data.type === "azents-github-installations-code" &&
      typeof event.data.code === "string" &&
      typeof event.data.state === "string"
    ) {
      popup.current = null;
      stop();
      setInstallationState("LOADING");
      void getInstallations
        .mutateAsync({
          handle: props.handle ?? "",
          agentId: props.agentId,
          code: event.data.code,
          state: event.data.state,
        })
        .then((data) => {
          setInstallations(data.installations);
          setInstallationState("READY");
        })
        .catch(() => setInstallationState("ERROR"));
    } else if (event.data.type === "azents-github-app-installed") {
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
    installations,
    selectedInstallations: targets(props.credentials?.installations),
    installationState,
    runtimeAcknowledged,
    canTest:
      Boolean(props.handle) &&
      ["pat", "github_app", "github_app_platform"].includes(
        String(props.config.github_auth_type),
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
      void utils.toolkit.githubUser.availability.invalidate({
        handle: props.handle ?? "",
        agentId: props.agentId,
      });
    },
    onRuntimeAcknowledged: setRuntimeAcknowledged,
    onConnectInstallations: () => {
      void connectInstallations();
    },
    onInstallApp: () => {
      void utils.toolkit.getGithubInstallUrl
        .fetch({ handle: props.handle ?? "", agentId: props.agentId })
        .then((data) =>
          open(data.install_url, () => {
            void connectInstallations();
          }),
        )
        .catch(() => setInstallationState("ERROR"));
    },
    onTest: () =>
      test.mutate({
        handle: props.handle ?? "",
        agentId: props.agentId,
        toolkitType: "github",
        toolkitConfigId: props.toolkitConfigId ?? null,
        config: props.config,
        credentials: props.credentials,
      }),
  };
}
