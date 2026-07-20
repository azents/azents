"use client";

/** GitHub toolkit configuration form fields. */

import {
  Alert,
  Avatar,
  Button,
  Checkbox,
  Group,
  Loader,
  MultiSelect,
  PasswordInput,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconBrandGithub,
  IconCheck,
  IconPlugConnected,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type { GitHubPlatformAuthorizationStateResponse } from "@azents/public-client";

type GithubConfig = Record<string, unknown>;
type GithubCredentials = Record<string, unknown> | null;

const GITHUB_AUTH_TYPE_OPTIONS = [
  { value: "pat", labelKey: "authTypePat" },
  { value: "github_app", labelKey: "authTypeApp" },
  { value: "github_app_platform", labelKey: "authTypePlatform" },
] as const;

const DEFAULT_TOOLSETS = ["repos", "issues", "pull_requests", "users"] as const;

const ALL_TOOLSETS = [
  "repos",
  "issues",
  "pull_requests",
  "users",
  "actions",
  "code_security",
  "notifications",
  "orgs",
  "projects",
  "discussions",
];

const TEST_SUPPORTED_AUTH_TYPES = new Set([
  "pat",
  "github_app",
  "github_app_platform",
]);

interface GithubConfigFieldsProps {
  config: GithubConfig;
  onConfigChange: (config: GithubConfig) => void;
  credentials: GithubCredentials;
  onCredentialsChange: (credentials: GithubCredentials) => void;
  hasCredentials: boolean;
  authorizationState: GitHubPlatformAuthorizationStateResponse | null;
  handle?: string;
  toolkitConfigId?: string;
}

interface TestResult {
  success: boolean;
  message: string;
}

interface InstallationItem {
  id: number;
  account_login: string;
  account_type: string;
  account_avatar_url: string;
}

interface InstallationTarget {
  installation_id: string;
  account_login: string;
  account_type: string;
  account_avatar_url: string | null;
}

function credentialInstallations(
  credentials: GithubCredentials,
): InstallationTarget[] {
  const raw = credentials?.installations;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((item) => {
    if (typeof item !== "object" || item === null) {
      return [];
    }
    const record = item as Record<string, unknown>;
    if (
      typeof record.installation_id !== "string" ||
      typeof record.account_login !== "string" ||
      typeof record.account_type !== "string"
    ) {
      return [];
    }
    return [
      {
        installation_id: record.installation_id,
        account_login: record.account_login,
        account_type: record.account_type,
        account_avatar_url:
          typeof record.account_avatar_url === "string"
            ? record.account_avatar_url
            : null,
      },
    ];
  });
}

function installationItemToTarget(item: InstallationItem): InstallationTarget {
  return {
    installation_id: String(item.id),
    account_login: item.account_login,
    account_type: item.account_type,
    account_avatar_url: item.account_avatar_url,
  };
}

export function GithubConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  authorizationState,
  handle,
  toolkitConfigId,
}: GithubConfigFieldsProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github");

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [runtimeEnvironmentAck, setRuntimeEnvironmentAck] = useState(false);
  const [installations, setInstallations] = useState<InstallationItem[]>([]);
  const [loadingInstallations, setLoadingInstallations] = useState(false);
  const [installationsLoaded, setInstallationsLoaded] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const testConnectionMutation = trpc.toolkit.testConnection.useMutation();
  const getInstallationsMutation =
    trpc.toolkit.getGithubInstallations.useMutation();
  const utils = trpc.useUtils();

  const selectedInstallations = credentialInstallations(credentials);

  const setConfig = (key: string, value: unknown): void => {
    onConfigChange({ ...config, [key]: value });
  };

  const setCred = (key: string, value: unknown): void => {
    onCredentialsChange({ ...(credentials ?? {}), [key]: value });
  };

  const setInstallationsCred = (targets: InstallationTarget[]): void => {
    onCredentialsChange({
      ...(credentials ?? {}),
      installations: targets,
    });
  };

  const stopPollingPopup = useCallback((): void => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    popupRef.current = null;
  }, []);

  const openPopupWithPolling = useCallback(
    (url: string, onClosed?: () => void): void => {
      stopPollingPopup();
      const popup = window.open(url, "github-popup", "width=1024,height=768");
      if (!popup) {
        return;
      }
      popupRef.current = popup;
      pollRef.current = setInterval(() => {
        if (popup.closed) {
          stopPollingPopup();
          onClosed?.();
        }
      }, 500);
    },
    [stopPollingPopup],
  );

  useEffect(() => {
    return () => stopPollingPopup();
  }, [stopPollingPopup]);

  const fetchInstallationsWithCode = useCallback(
    async (code: string, state: string): Promise<void> => {
      setLoadingInstallations(true);
      try {
        const data = await getInstallationsMutation.mutateAsync({
          handle: handle ?? "",
          code,
          state,
        });
        setInstallations(data.installations);
        setInstallationsLoaded(true);
      } catch {
        setInstallations([]);
      } finally {
        setLoadingInstallations(false);
      }
    },
    [getInstallationsMutation, handle],
  );

  const startOAuthFlow = useCallback(async (): Promise<void> => {
    setLoadingInstallations(true);
    try {
      const data = await utils.toolkit.getGithubOauthUrl.fetch({
        handle: handle ?? "",
      });
      if (data.oauth_url) {
        openPopupWithPolling(data.oauth_url);
      } else {
        setLoadingInstallations(false);
      }
    } catch {
      setLoadingInstallations(false);
    }
  }, [utils.toolkit.getGithubOauthUrl, openPopupWithPolling, handle]);

  const handleInstallApp = useCallback(async (): Promise<void> => {
    try {
      const data = await utils.toolkit.getGithubInstallUrl.fetch({
        handle: handle ?? "",
      });
      if (data.install_url) {
        openPopupWithPolling(data.install_url, () => {
          void startOAuthFlow();
        });
      }
    } catch {
      // Keep GitHub install URL lookup failures local to this form for now.
    }
  }, [
    utils.toolkit.getGithubInstallUrl,
    openPopupWithPolling,
    startOAuthFlow,
    handle,
  ]);

  const handleMessage = useCallback(
    (event: MessageEvent<unknown>): void => {
      if (event.origin !== window.location.origin) {
        return;
      }
      if (popupRef.current && event.source !== popupRef.current) {
        return;
      }
      const data = event.data;
      if (typeof data !== "object" || data === null || !("type" in data)) {
        return;
      }

      const msgType = (data as Record<string, unknown>).type;
      if (msgType === "azents-github-installations-code") {
        const code = (data as Record<string, unknown>).code;
        const state = (data as Record<string, unknown>).state;
        if (
          typeof code === "string" &&
          code &&
          typeof state === "string" &&
          state
        ) {
          void fetchInstallationsWithCode(code, state);
        }
        stopPollingPopup();
      }
      if (msgType === "azents-github-app-installed") {
        stopPollingPopup();
        void startOAuthFlow();
      }
    },
    [fetchInstallationsWithCode, stopPollingPopup, startOAuthFlow],
  );

  useEffect(() => {
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [handleMessage]);

  const handleTestConnection = async (): Promise<void> => {
    if (!handle) {
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testConnectionMutation.mutateAsync({
        handle,
        toolkitType: "github",
        toolkitConfigId: toolkitConfigId ?? null,
        config,
        credentials,
      });
      setTestResult({
        success: result.success,
        message: result.success
          ? t("testConnectionSuccess")
          : t("testConnectionFailed", { message: result.message }),
      });
    } catch (error) {
      setTestResult({
        success: false,
        message: t("testConnectionFailed", {
          message: error instanceof Error ? error.message : "Unknown error",
        }),
      });
    } finally {
      setTesting(false);
    }
  };

  const handleAuthTypeChange = (value: string | null): void => {
    const newType = value ?? "pat";
    onConfigChange({
      ...config,
      github_auth_type: newType,
      auth_type: "bearer",
    });
    onCredentialsChange({ type: newType });
  };

  const updateByoaInstallation = (
    index: number,
    key: keyof InstallationTarget,
    value: string,
  ): void => {
    const current = selectedInstallations[index];
    if (!current) {
      return;
    }
    const next = [...selectedInstallations];
    next[index] = { ...current, [key]: value };
    setInstallationsCred(next);
  };

  const addByoaInstallation = (): void => {
    setInstallationsCred([
      ...selectedInstallations,
      {
        installation_id: "",
        account_login: "",
        account_type: "Organization",
        account_avatar_url: null,
      },
    ]);
  };

  const removeByoaInstallation = (index: number): void => {
    setInstallationsCred(selectedInstallations.filter((_, i) => i !== index));
  };

  const handlePlatformSelection = (values: string[]): void => {
    const fromLoaded = values.flatMap((value) => {
      const item = installations.find((inst) => String(inst.id) === value);
      return item ? [installationItemToTarget(item)] : [];
    });
    const existing = selectedInstallations.filter((target) =>
      values.includes(target.installation_id),
    );
    const byId = new Map<string, InstallationTarget>();
    for (const target of [...existing, ...fromLoaded]) {
      byId.set(target.installation_id, target);
    }
    setInstallationsCred([...byId.values()]);
  };

  const githubAuthType = (config.github_auth_type as string) || "pat";
  const toolsets = Array.isArray(config.toolsets)
    ? (config.toolsets as string[])
    : [...DEFAULT_TOOLSETS];
  const canTest = TEST_SUPPORTED_AUTH_TYPES.has(githubAuthType);

  const installationSelectData = installations.map((inst) => ({
    value: String(inst.id),
    label: `${inst.account_login} (${inst.account_type})`,
  }));

  return (
    <Stack gap="sm">
      <Select
        label={t("authTypeLabel")}
        data={GITHUB_AUTH_TYPE_OPTIONS.map((opt) => ({
          value: opt.value,
          label: t(opt.labelKey),
        }))}
        value={githubAuthType}
        onChange={handleAuthTypeChange}
      />

      {githubAuthType === "pat" && (
        <PasswordInput
          label={t("patTokenLabel")}
          description={t("patTokenDescription")}
          placeholder={
            hasCredentials
              ? t("credentialsEditPlaceholder")
              : "Paste a GitHub token"
          }
          value={(credentials?.token as string) || ""}
          onChange={(e) => setCred("token", e.currentTarget.value)}
        />
      )}

      {githubAuthType === "github_app" && (
        <>
          <TextInput
            label={t("appIdLabel")}
            placeholder="123456"
            required
            value={(credentials?.app_id as string) || ""}
            onChange={(e) => setCred("app_id", e.currentTarget.value)}
          />
          <Textarea
            label={t("privateKeyLabel")}
            description={t("privateKeyDescription")}
            placeholder={
              hasCredentials
                ? t("credentialsEditPlaceholder")
                : "Paste a GitHub App private key"
            }
            autosize
            minRows={3}
            maxRows={8}
            value={(credentials?.private_key as string) || ""}
            onChange={(e) => setCred("private_key", e.currentTarget.value)}
            styles={{
              input: { fontFamily: "var(--font-geist-mono)" },
            }}
          />
          <Stack gap="xs">
            <Text size="sm" fw={500}>
              {t("installationsLabel")}
            </Text>
            <Text size="xs" c="dimmed">
              {t("installationsDescription")}
            </Text>
            {selectedInstallations.map((target, index) => (
              <Group key={index} align="flex-end" gap="xs">
                <TextInput
                  label={t("installationIdLabel")}
                  placeholder="12345678"
                  required
                  value={target.installation_id}
                  onChange={(e) =>
                    updateByoaInstallation(
                      index,
                      "installation_id",
                      e.currentTarget.value,
                    )
                  }
                />
                <TextInput
                  label={t("accountLoginLabel")}
                  placeholder="azents"
                  required
                  value={target.account_login}
                  onChange={(e) =>
                    updateByoaInstallation(
                      index,
                      "account_login",
                      e.currentTarget.value,
                    )
                  }
                />
                <Select
                  label={t("accountTypeLabel")}
                  data={["Organization", "User"]}
                  value={target.account_type}
                  onChange={(value) =>
                    updateByoaInstallation(
                      index,
                      "account_type",
                      value ?? "Organization",
                    )
                  }
                />
                <Button
                  variant="subtle"
                  color="red"
                  leftSection={<IconTrash size={14} />}
                  onClick={() => removeByoaInstallation(index)}
                >
                  {t("removeInstallation")}
                </Button>
              </Group>
            ))}
            <Button
              variant="light"
              leftSection={<IconPlus size={14} />}
              onClick={addByoaInstallation}
              w="fit-content"
            >
              {t("addInstallation")}
            </Button>
          </Stack>
        </>
      )}

      {githubAuthType === "github_app_platform" && (
        <>
          {authorizationState?.status === "reconnect_required" && (
            <Alert
              color="red"
              variant="light"
              icon={<IconAlertTriangle size={16} />}
              title={t("reconnectRequiredTitle")}
            >
              <Stack gap="xs">
                <Text size="sm">{t("reconnectReasonAppIdentityChanged")}</Text>
                <Button
                  variant="light"
                  color="red"
                  leftSection={<IconBrandGithub size={16} />}
                  onClick={() => void startOAuthFlow()}
                  loading={loadingInstallations}
                  w="fit-content"
                >
                  {t("reconnectGithub")}
                </Button>
              </Stack>
            </Alert>
          )}

          <Alert color="blue" variant="light">
            <Text size="sm">{t("platformDescription")}</Text>
          </Alert>

          {!installationsLoaded && selectedInstallations.length === 0 && (
            <Button
              variant="light"
              leftSection={<IconBrandGithub size={16} />}
              onClick={() => void startOAuthFlow()}
              loading={loadingInstallations}
            >
              {t("connectGithub")}
            </Button>
          )}

          {loadingInstallations && installationsLoaded && (
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                {t("loadingInstallations")}
              </Text>
            </Group>
          )}

          {installationsLoaded && !loadingInstallations && (
            <>
              {installationSelectData.length > 0 ? (
                <MultiSelect
                  label={t("selectInstallationLabel")}
                  description={t("selectInstallationDescription")}
                  data={installationSelectData}
                  value={selectedInstallations.map(
                    (target) => target.installation_id,
                  )}
                  onChange={handlePlatformSelection}
                  renderOption={({ option }) => {
                    const inst = installations.find(
                      (i) => String(i.id) === option.value,
                    );
                    return (
                      <Group gap="sm">
                        {inst && (
                          <Avatar
                            src={inst.account_avatar_url}
                            size="sm"
                            radius="xl"
                          />
                        )}
                        <Text size="sm">{option.label}</Text>
                      </Group>
                    );
                  }}
                />
              ) : (
                <Alert color="yellow" variant="light">
                  <Text size="sm">{t("noInstallationsFound")}</Text>
                </Alert>
              )}
              <Group gap="xs">
                <Button
                  variant="subtle"
                  size="compact-sm"
                  leftSection={<IconBrandGithub size={14} />}
                  onClick={() => void startOAuthFlow()}
                  w="fit-content"
                >
                  {t("refreshInstallations")}
                </Button>
                <Button
                  variant="subtle"
                  size="compact-sm"
                  leftSection={<IconPlus size={14} />}
                  onClick={() => void handleInstallApp()}
                  w="fit-content"
                >
                  {t("installNewOrg")}
                </Button>
              </Group>
            </>
          )}

          {selectedInstallations.length > 0 && (
            <Alert icon={<IconCheck size={16} />} color="green" variant="light">
              <Stack gap={4}>
                <Text size="sm">{t("installationsLinked")}</Text>
                {selectedInstallations.map((target) => (
                  <Text key={target.installation_id} size="xs" c="dimmed">
                    {target.account_login} ({target.account_type}) —{" "}
                    {target.installation_id}
                  </Text>
                ))}
              </Stack>
            </Alert>
          )}
        </>
      )}

      {hasCredentials && (
        <Text size="xs" c="dimmed">
          {t("credentialsSetHint")}
        </Text>
      )}

      <TagsInput
        label={t("toolsetsLabel")}
        description={t("toolsetsDescription")}
        data={ALL_TOOLSETS}
        value={toolsets}
        onChange={(v) => setConfig("toolsets", v)}
      />

      <Alert
        variant="light"
        color="orange"
        icon={<IconAlertTriangle size={16} />}
        title={t("runtimeEnvironmentWarningTitle")}
      >
        <Stack gap="xs">
          <Text size="sm">{t("runtimeEnvironmentWarningBody")}</Text>
          <Checkbox
            checked={runtimeEnvironmentAck}
            onChange={(e) => setRuntimeEnvironmentAck(e.currentTarget.checked)}
            label={t("runtimeEnvironmentAcknowledge")}
          />
          <Switch
            checked={Boolean(config.inject_runtime_environment)}
            onChange={(e) =>
              setConfig("inject_runtime_environment", e.currentTarget.checked)
            }
            label={t("runtimeEnvironmentToggle")}
            description={t("runtimeEnvironmentToggleDescription")}
            disabled={
              !runtimeEnvironmentAck && !config.inject_runtime_environment
            }
          />
        </Stack>
      </Alert>

      {handle && canTest && (
        <Button
          variant="light"
          leftSection={<IconPlugConnected size={16} />}
          onClick={() => void handleTestConnection()}
          loading={testing}
          disabled={authorizationState?.status === "reconnect_required"}
          w="fit-content"
        >
          {t("testConnection")}
        </Button>
      )}

      {testResult && (
        <Alert color={testResult.success ? "green" : "red"}>
          <Text size="sm">{testResult.message}</Text>
        </Alert>
      )}
    </Stack>
  );
}
