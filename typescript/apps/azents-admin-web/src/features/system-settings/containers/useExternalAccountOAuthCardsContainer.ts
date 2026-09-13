"use client";

import { IconBrandDiscord, IconBrandSlack } from "@tabler/icons-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  ExternalAccountOAuthDetailResponse,
  ExternalAccountOAuthFieldResponse,
} from "@azents/admin-client";

export type ExternalAccountOAuthProvider = "slack" | "discord";
export type ExternalAccountOAuthClientField = "client_id" | "application_id";

export interface ExternalAccountOAuthCardConfig {
  provider: ExternalAccountOAuthProvider;
  title: string;
  description: string;
  clientField: ExternalAccountOAuthClientField;
  clientLabel: string;
  Icon: typeof IconBrandSlack;
}

export const SLACK_EXTERNAL_ACCOUNT_OAUTH_CONFIG: ExternalAccountOAuthCardConfig =
  {
    provider: "slack",
    title: "Slack account authorization",
    description:
      "Configure the Slack OAuth App used to connect a User identity. This does not change External Channel connection credentials.",
    clientField: "client_id",
    clientLabel: "Client ID",
    Icon: IconBrandSlack,
  };

export const DISCORD_EXTERNAL_ACCOUNT_OAUTH_CONFIG: ExternalAccountOAuthCardConfig =
  {
    provider: "discord",
    title: "Discord account authorization",
    description:
      "Configure the Discord Application used to connect a User identity. This does not change External Channel connection credentials.",
    clientField: "application_id",
    clientLabel: "Application ID",
    Icon: IconBrandDiscord,
  };

export const EXTERNAL_ACCOUNT_OAUTH_CARD_CONFIGS: ExternalAccountOAuthCardConfig[] =
  [SLACK_EXTERNAL_ACCOUNT_OAUTH_CONFIG, DISCORD_EXTERNAL_ACCOUNT_OAUTH_CONFIG];

export interface ExternalAccountOAuthDraft {
  clientValue: string;
  clientTouched: boolean;
  clientSecret: string;
  clearClientSecret: boolean;
}

export type ExternalAccountOAuthCardState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      detail: ExternalAccountOAuthDetailResponse;
      draft: ExternalAccountOAuthDraft;
      dirty: boolean;
      mutationError: string | null;
      saving: boolean;
      checkingHealth: boolean;
      onClientValueChange: (value: string) => void;
      onClientSecretChange: (value: string) => void;
      onClearClientSecretChange: (checked: boolean) => void;
      onCheckHealth: () => void;
      onSave: () => void;
    };

export interface ExternalAccountOAuthCardContainerProps {
  config: ExternalAccountOAuthCardConfig;
  state: ExternalAccountOAuthCardState;
}

export interface ExternalAccountOAuthCardsContainerProps {
  cards: ExternalAccountOAuthCardContainerProps[];
}

interface SecretActionReplace {
  action: "replace";
  value: string;
}

interface SecretActionClear {
  action: "clear";
}

type SecretAction = SecretActionReplace | SecretActionClear;

function findField(
  detail: ExternalAccountOAuthDetailResponse,
  name: string,
): ExternalAccountOAuthFieldResponse | null {
  return detail.fields.find((field) => field.name === name) ?? null;
}

function secretAction(
  clearClientSecret: boolean,
  clientSecret: string,
): SecretAction | null {
  if (clearClientSecret) {
    return { action: "clear" };
  }
  if (clientSecret.length > 0) {
    return { action: "replace", value: clientSecret };
  }
  return null;
}

function useExternalAccountOAuthCardContainer(
  config: ExternalAccountOAuthCardConfig,
): ExternalAccountOAuthCardState {
  const utils = trpc.useUtils();
  const query = trpc.systemSettings.getExternalAccountOAuth.useQuery({
    provider: config.provider,
  });
  const [draft, setDraft] = useState<ExternalAccountOAuthDraft>({
    clientValue: "",
    clientTouched: false,
    clientSecret: "",
    clearClientSecret: false,
  });
  const initializedVersion = useRef<number | null>(null);

  useEffect(() => {
    const detail = query.data;
    if (!detail || initializedVersion.current === detail.admin_version) {
      return;
    }
    initializedVersion.current = detail.admin_version;
    const clientField = findField(detail, config.clientField);
    setDraft({
      clientValue: clientField?.value ?? "",
      clientTouched: false,
      clientSecret: "",
      clearClientSecret: false,
    });
  }, [config.clientField, query.data]);

  const invalidate = useCallback(async (): Promise<void> => {
    await Promise.all([
      utils.systemSettings.getExternalAccountOAuth.invalidate({
        provider: config.provider,
      }),
      utils.systemSettings.listAuditEvents.invalidate(),
    ]);
  }, [config.provider, utils.systemSettings]);

  const patchMutation =
    trpc.systemSettings.patchExternalAccountOAuth.useMutation({
      onSuccess: async () => {
        setDraft((current) => ({
          ...current,
          clientSecret: "",
          clientTouched: false,
          clearClientSecret: false,
        }));
        await invalidate();
      },
      onError: () => {
        void utils.systemSettings.getExternalAccountOAuth.invalidate({
          provider: config.provider,
        });
      },
    });
  const healthMutation =
    trpc.systemSettings.checkExternalAccountOAuthHealth.useMutation({
      onSuccess: invalidate,
    });

  const onClientValueChange = useCallback((value: string): void => {
    setDraft((current) => ({
      ...current,
      clientValue: value,
      clientTouched: true,
    }));
  }, []);

  const onClientSecretChange = useCallback((value: string): void => {
    setDraft((current) => ({
      ...current,
      clientSecret: value,
      clearClientSecret: false,
    }));
  }, []);

  const onClearClientSecretChange = useCallback((checked: boolean): void => {
    setDraft((current) => ({
      ...current,
      clientSecret: checked ? "" : current.clientSecret,
      clearClientSecret: checked,
    }));
  }, []);

  if (query.isPending) {
    return { type: "LOADING" };
  }

  if (query.isError) {
    return { type: "ERROR", message: query.error.message };
  }

  const detail = query.data;

  const draftSecretAction = secretAction(
    draft.clearClientSecret,
    draft.clientSecret,
  );
  const dirty = draft.clientTouched || draftSecretAction !== null;

  const onCheckHealth = (): void => {
    healthMutation.mutate({ provider: config.provider });
  };

  const onSave = (): void => {
    if (!dirty) {
      return;
    }
    patchMutation.mutate({
      provider: config.provider,
      expectedVersion: detail.admin_version,
      ...(draft.clientTouched
        ? config.clientField === "client_id"
          ? { clientId: draft.clientValue.trim() || null }
          : { applicationId: draft.clientValue.trim() || null }
        : {}),
      ...(draftSecretAction ? { clientSecret: draftSecretAction } : {}),
    });
  };

  return {
    type: "LOADED",
    detail,
    draft,
    dirty,
    mutationError:
      patchMutation.error?.message ?? healthMutation.error?.message ?? null,
    saving: patchMutation.isPending,
    checkingHealth: healthMutation.isPending,
    onClientValueChange,
    onClientSecretChange,
    onClearClientSecretChange,
    onCheckHealth,
    onSave,
  };
}

export function useExternalAccountOAuthCardsContainer(): ExternalAccountOAuthCardsContainerProps {
  const slack = useExternalAccountOAuthCardContainer(
    SLACK_EXTERNAL_ACCOUNT_OAUTH_CONFIG,
  );
  const discord = useExternalAccountOAuthCardContainer(
    DISCORD_EXTERNAL_ACCOUNT_OAUTH_CONFIG,
  );
  return {
    cards: [
      { config: SLACK_EXTERNAL_ACCOUNT_OAUTH_CONFIG, state: slack },
      { config: DISCORD_EXTERNAL_ACCOUNT_OAUTH_CONFIG, state: discord },
    ],
  };
}
