import {
  Alert,
  Anchor,
  Avatar,
  Button,
  Checkbox,
  Group,
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
import { useTranslations } from "next-intl";
import { getString, getStringArray } from "@/shared/lib/unknown-value";
import { isGitHubUserMode } from "../github-user-oauth-state";
import type { GitHubAvailabilityState } from "../github-user-oauth-state";
import type { GitHubPlatformAuthorizationStateResponse } from "@azents/public-client";

export interface InstallationTarget {
  installation_id: string;
  account_login: string;
  account_type: string;
  account_avatar_url: string | null;
}
export interface InstallationItem {
  id: number;
  account_login: string;
  account_type: string;
  account_avatar_url: string;
}
export interface GithubFieldsViewProps {
  config: Record<string, unknown>;
  credentials: Record<string, unknown> | null;
  hasCredentials: boolean;
  savedUserRegistration: boolean;
  authorizationState: GitHubPlatformAuthorizationStateResponse | null;
  availability: GitHubAvailabilityState;
  installations: InstallationItem[];
  selectedInstallations: InstallationTarget[];
  installationState: "IDLE" | "LOADING" | "READY" | "ERROR";
  testState:
    | { type: "IDLE" }
    | { type: "TESTING" }
    | { type: "RESULT"; success: boolean; message: string };
  runtimeAcknowledged: boolean;
  canTest: boolean;
  onRetryAvailability: () => void;
  onConfigChange: (config: Record<string, unknown>) => void;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  onConnectInstallations: () => void;
  onInstallApp: () => void;
  onTest: () => void;
  onRuntimeAcknowledged: (value: boolean) => void;
}
const options = [
  { value: "pat", labelKey: "authTypePat" },
  { value: "github_app", labelKey: "authTypeApp" },
  { value: "github_app_platform", labelKey: "authTypePlatform" },
  { value: "github_app_user", labelKey: "authTypeUser" },
  { value: "github_app_platform_user", labelKey: "authTypePlatformUser" },
] as const;
const toolsets = [
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

export function GithubFieldsView(
  props: GithubFieldsViewProps,
): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github");
  const auth = getString(props.config.github_auth_type) || "pat";
  const userMode = isGitHubUserMode(auth);
  const unavailable =
    props.availability.type === "READY" &&
    props.availability.availability.platform === "absent";
  const platformSaved =
    auth === "github_app_platform" || auth === "github_app_platform_user";
  function setCred(key: string, value: unknown): void {
    props.onCredentialsChange({ ...props.credentials, [key]: value });
  }
  function setConfig(key: string, value: unknown): void {
    props.onConfigChange({ ...props.config, [key]: value });
  }
  function setTargets(targets: InstallationTarget[]): void {
    setCred("installations", targets);
  }
  function updateTarget(
    index: number,
    key: keyof InstallationTarget,
    value: string,
  ): void {
    setTargets(
      props.selectedInstallations.map((target, i) =>
        i === index ? { ...target, [key]: value } : target,
      ),
    );
  }
  function selectTargets(values: string[]): void {
    const targets = new Map(
      props.selectedInstallations
        .filter((target) => values.includes(target.installation_id))
        .map((target) => [target.installation_id, target]),
    );
    for (const item of props.installations) {
      if (values.includes(String(item.id))) {
        targets.set(String(item.id), {
          installation_id: String(item.id),
          account_login: item.account_login,
          account_type: item.account_type,
          account_avatar_url: item.account_avatar_url,
        });
      }
    }
    setTargets([...targets.values()]);
  }
  return (
    <Stack gap="sm">
      {props.availability.type === "LOADING" && (
        <Text size="sm" c="dimmed">
          {t("availabilityLoading")}
        </Text>
      )}
      {props.availability.type === "ERROR" && (
        <Alert color="yellow">
          <Stack gap="xs">
            <Text size="sm">{t("availabilityError")}</Text>
            <Button variant="subtle" onClick={props.onRetryAvailability}>
              {t("retry")}
            </Button>
          </Stack>
        </Alert>
      )}
      {props.availability.type === "READY" &&
        props.availability.availability.platform === "incomplete" && (
          <Alert color="yellow">{t("platformIncomplete")}</Alert>
        )}
      {unavailable && platformSaved && (
        <Alert color="yellow">{t("savedPlatformAbsent")}</Alert>
      )}
      <Select
        label={t("authTypeLabel")}
        data={options
          .filter(
            (option) =>
              !unavailable || !option.value.startsWith("github_app_platform"),
          )
          .map((option) => ({
            value: option.value,
            label: t(option.labelKey),
          }))}
        value={auth}
        onChange={(value) => {
          const next = value ?? "pat";
          props.onConfigChange({
            ...props.config,
            github_auth_type: next,
            auth_type: "bearer",
          });
          props.onCredentialsChange({ type: next });
        }}
      />
      {unavailable && platformSaved && (
        <Text size="sm">
          {t(
            auth === "github_app_platform_user"
              ? "authTypePlatformUser"
              : "authTypePlatform",
          )}
        </Text>
      )}
      {auth === "pat" && (
        <PasswordInput
          label={t("patTokenLabel")}
          description={t("patTokenDescription")}
          placeholder={
            props.hasCredentials ? t("credentialsEditPlaceholder") : void 0
          }
          value={getString(props.credentials?.token)}
          onChange={(event) => setCred("token", event.currentTarget.value)}
        />
      )}
      {(auth === "github_app" || auth === "github_app_user") && (
        <>
          <TextInput
            label={t("appIdLabel")}
            required={auth === "github_app" || !props.savedUserRegistration}
            placeholder={
              props.savedUserRegistration
                ? t("credentialsEditPlaceholder")
                : "123456"
            }
            value={getString(props.credentials?.app_id)}
            onChange={(event) => setCred("app_id", event.currentTarget.value)}
          />
          <Textarea
            label={t("privateKeyLabel")}
            description={t("privateKeyDescription")}
            required={
              auth === "github_app_user" && !props.savedUserRegistration
            }
            placeholder={
              props.hasCredentials ? t("credentialsEditPlaceholder") : void 0
            }
            autosize
            minRows={3}
            maxRows={8}
            value={getString(props.credentials?.private_key)}
            onChange={(event) =>
              setCred("private_key", event.currentTarget.value)
            }
            styles={{ input: { fontFamily: "var(--font-geist-mono)" } }}
          />
        </>
      )}
      {auth === "github_app_user" && (
        <>
          <TextInput
            label={t("clientIdLabel")}
            required={!props.savedUserRegistration}
            placeholder={
              props.savedUserRegistration
                ? t("credentialsEditPlaceholder")
                : void 0
            }
            value={getString(props.credentials?.client_id)}
            onChange={(event) =>
              setCred("client_id", event.currentTarget.value)
            }
          />
          <PasswordInput
            label={t("clientSecretLabel")}
            required={!props.savedUserRegistration}
            placeholder={
              props.savedUserRegistration
                ? t("credentialsEditPlaceholder")
                : void 0
            }
            value={getString(props.credentials?.client_secret)}
            onChange={(event) =>
              setCred("client_secret", event.currentTarget.value)
            }
          />
          {props.savedUserRegistration && (
            <Text size="xs" c="dimmed">
              {t("registrationEditHint")}
            </Text>
          )}
        </>
      )}
      {userMode && (
        <Alert color="blue">
          <Stack gap="xs">
            <Text size="sm">
              {t(
                auth === "github_app_user"
                  ? "userRegistrationInstructions"
                  : "platformUserInstructions",
              )}
            </Text>
            <Text size="sm">{t("callbackLabel")}</Text>
            <Text size="sm" style={{ overflowWrap: "anywhere" }}>
              {props.availability.type === "READY"
                ? (props.availability.availability.callback_url ??
                  t("callbackUnavailable"))
                : t("availabilityLoading")}
            </Text>
            <Anchor
              href="https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app"
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("registrationHelp")}
            </Anchor>
            <Text size="sm">{t("saveBeforeAuthorize")}</Text>
          </Stack>
        </Alert>
      )}
      {auth === "github_app" && (
        <Stack gap="xs">
          <Text size="sm" fw={500}>
            {t("installationsLabel")}
          </Text>
          <Text size="xs" c="dimmed">
            {t("installationsDescription")}
          </Text>
          {props.selectedInstallations.map((target, index) => (
            <Group key={index} align="flex-end" gap="xs">
              <TextInput
                label={t("installationIdLabel")}
                required
                value={target.installation_id}
                onChange={(event) =>
                  updateTarget(
                    index,
                    "installation_id",
                    event.currentTarget.value,
                  )
                }
              />
              <TextInput
                label={t("accountLoginLabel")}
                required
                value={target.account_login}
                onChange={(event) =>
                  updateTarget(
                    index,
                    "account_login",
                    event.currentTarget.value,
                  )
                }
              />
              <Select
                label={t("accountTypeLabel")}
                data={["Organization", "User"]}
                value={target.account_type}
                onChange={(value) =>
                  updateTarget(index, "account_type", value ?? "Organization")
                }
              />
              <Button
                variant="subtle"
                color="red"
                onClick={() =>
                  setTargets(
                    props.selectedInstallations.filter((_, i) => i !== index),
                  )
                }
              >
                {t("removeInstallation")}
              </Button>
            </Group>
          ))}
          <Button
            variant="light"
            w="fit-content"
            onClick={() =>
              setTargets([
                ...props.selectedInstallations,
                {
                  installation_id: "",
                  account_login: "",
                  account_type: "Organization",
                  account_avatar_url: null,
                },
              ])
            }
          >
            {t("addInstallation")}
          </Button>
        </Stack>
      )}
      {auth === "github_app_platform" && (
        <>
          {props.authorizationState?.status === "reconnect_required" && (
            <Alert color="red" title={t("reconnectRequiredTitle")}>
              {t("reconnectReasonAppIdentityChanged")}
            </Alert>
          )}
          <Alert color="blue">{t("platformDescription")}</Alert>
          {props.installationState === "ERROR" && (
            <Alert color="red">{t("installationLoadError")}</Alert>
          )}
          <Button
            variant="light"
            onClick={props.onConnectInstallations}
            loading={props.installationState === "LOADING"}
            disabled={unavailable}
          >
            {t(
              props.selectedInstallations.length > 0
                ? "refreshInstallations"
                : "connectGithub",
            )}
          </Button>
          {props.installationState === "READY" &&
            (props.installations.length > 0 ? (
              <MultiSelect
                label={t("selectInstallationLabel")}
                description={t("selectInstallationDescription")}
                data={props.installations.map((item) => ({
                  value: String(item.id),
                  label: `${item.account_login} (${item.account_type})`,
                }))}
                value={props.selectedInstallations.map(
                  (target) => target.installation_id,
                )}
                onChange={selectTargets}
              />
            ) : (
              <Alert color="yellow">{t("noInstallationsFound")}</Alert>
            ))}
          <Button
            variant="subtle"
            onClick={props.onInstallApp}
            disabled={unavailable}
          >
            {t("installNewOrg")}
          </Button>
          {props.selectedInstallations.length > 0 && (
            <Alert color="green">
              <Stack gap="xs">
                <Text>{t("installationsLinked")}</Text>
                {props.selectedInstallations.map((target) => (
                  <Group key={target.installation_id}>
                    <Avatar src={target.account_avatar_url} size="sm" />
                    <Text size="xs">
                      {target.account_login} ({target.account_type}) —{" "}
                      {target.installation_id}
                    </Text>
                  </Group>
                ))}
              </Stack>
            </Alert>
          )}
        </>
      )}
      {props.hasCredentials && (
        <Text size="xs" c="dimmed">
          {t("credentialsSetHint")}
        </Text>
      )}
      <TagsInput
        label={t("toolsetsLabel")}
        description={t("toolsetsDescription")}
        data={toolsets}
        value={
          Array.isArray(props.config.toolsets)
            ? getStringArray(props.config.toolsets)
            : ["repos", "issues", "pull_requests", "users"]
        }
        onChange={(value) => setConfig("toolsets", value)}
      />
      <Alert
        color="orange"
        title={t("runtimeEnvironmentWarningTitle")}
        styles={{ body: { minWidth: 0, overflowWrap: "anywhere" } }}
      >
        <Stack gap="xs">
          <Text size="sm">
            {t(
              userMode ? "userRuntimeWarning" : "runtimeEnvironmentWarningBody",
            )}
          </Text>
          <Checkbox
            checked={props.runtimeAcknowledged}
            onChange={(event) =>
              props.onRuntimeAcknowledged(event.currentTarget.checked)
            }
            label={t("runtimeEnvironmentAcknowledge")}
          />
          <Switch
            label={t("runtimeEnvironmentToggle")}
            description={t(
              userMode
                ? "userRuntimeDescription"
                : "runtimeEnvironmentToggleDescription",
            )}
            checked={Boolean(props.config.inject_runtime_environment)}
            disabled={
              !props.runtimeAcknowledged &&
              !props.config.inject_runtime_environment
            }
            onChange={(event) =>
              setConfig(
                "inject_runtime_environment",
                event.currentTarget.checked,
              )
            }
          />
        </Stack>
      </Alert>
      {props.canTest && (
        <Button
          variant="light"
          loading={props.testState.type === "TESTING"}
          disabled={props.authorizationState?.status === "reconnect_required"}
          onClick={props.onTest}
        >
          {t("testConnection")}
        </Button>
      )}
      {props.testState.type === "RESULT" && (
        <Alert color={props.testState.success ? "green" : "red"}>
          {props.testState.message}
        </Alert>
      )}
    </Stack>
  );
}
