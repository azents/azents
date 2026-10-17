import {
  Accordion,
  Alert,
  Anchor,
  Avatar,
  Badge,
  Button,
  Checkbox,
  Container,
  Group,
  Loader,
  MultiSelect,
  NumberInput,
  PasswordInput,
  SimpleGrid,
  Stack,
  Switch,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
  VisuallyHidden,
} from "@mantine/core";
import {
  IconArrowRight,
  IconBrandGithub,
  IconExternalLink,
  IconKey,
  IconLock,
  IconRefresh,
  IconShieldCheck,
  IconUser,
  IconUsers,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { GITHUB_WIZARD_STEPS } from "../github-wizard-progression";
import {
  GITHUB_FEATURE_GROUPS,
  gitHubWizardConnectionReady,
  isKnownGitHubFeature,
  wizardMode,
} from "../github-wizard-state";
import classes from "./GitHubWizard.module.css";
import { GitHubWizardCallbackHelp } from "./GitHubWizardCallbackHelp";
import { GitHubWizardChoice } from "./GitHubWizardChoice";
import { GitHubWizardSection } from "./GitHubWizardSection";
import type { GitHubWizardStep } from "../github-wizard-progression";
import type {
  GitHubWizardAppState,
  GitHubWizardAvailability,
  GitHubWizardConnection,
  GitHubWizardCredentials,
  GitHubWizardIdentity,
  GitHubWizardMode,
  GitHubWizardPublication,
  GitHubWizardSettings,
} from "../github-wizard-state";
import type { GitHubUserCandidateSummary } from "@azents/public-client";
import type { RefObject } from "react";

export interface GitHubWizardProps {
  embedded: boolean;
  registrationGuideHref?: string;
  sharingScope: "workspace_shared" | "agent_only" | "personal";
  identity: GitHubWizardIdentity | null;
  mode: GitHubWizardMode | null;
  availability: GitHubWizardAvailability;
  platformApp: GitHubWizardAppState;
  connection: GitHubWizardConnection;
  credentials: GitHubWizardCredentials;
  settings: GitHubWizardSettings;
  stage: "CONNECTION" | "FEATURES" | "RUNTIME" | "REVIEW";
  publication: GitHubWizardPublication;
  candidate: GitHubUserCandidateSummary | null;
  installationState:
    | { type: "IDLE" }
    | { type: "LOADING" }
    | { type: "ERROR" }
    | {
        type: "READY";
        installations: {
          id: number;
          account_login: string;
          account_type: string;
        }[];
      };
  rootRef?: RefObject<HTMLDivElement | null>;
  canContinue: boolean;
  onIdentity: (identity: GitHubWizardIdentity) => void;
  onMode: (mode: GitHubWizardMode) => void;
  onCredentials: (credentials: GitHubWizardCredentials) => void;
  onSettings: (settings: GitHubWizardSettings) => void;
  onConnect: () => void;
  onRetryMetadata: () => void;
  onRetryPlatformMetadata: () => void;
  onRetryAvailability: () => void;
  onContinue: () => void;
  onReset: () => void;
  onClose: () => void;
  onInspect: () => void;
  onPublish: () => void;
  onConnectInstallations: () => void;
  onInstallApp: () => void;
}

function AppMetadata({
  state,
  onRetry,
}: {
  state: GitHubWizardAppState;
  onRetry: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github.wizard");
  switch (state.type) {
    case "LOADING":
      return (
        <Group>
          <Loader size="xs" />
          <Text size="sm">{t("metadataLoading")}</Text>
        </Group>
      );
    case "ERROR":
      return (
        <Alert color="yellow">
          <Stack gap="xs">
            <Text>{state.message}</Text>
            <Button variant="subtle" onClick={onRetry}>
              {t("retry")}
            </Button>
          </Stack>
        </Alert>
      );
    case "READY":
      return (
        <Text size="sm">{t("platformMethod", { name: state.app.name })}</Text>
      );
  }
}
function ConnectionEvidence({
  connection,
  onRetry,
}: {
  connection: GitHubWizardConnection;
  onRetry: () => void;
}): React.ReactElement | null {
  const t = useTranslations("workspace.toolkits.github.wizard");
  switch (connection.type) {
    case "INPUT":
      return null;
    case "LOADING":
      return (
        <Group role="status">
          <Loader size="sm" />
          <Text>{t("verifying")}</Text>
        </Group>
      );
    case "ERROR":
      return (
        <Alert color="red" role="alert">
          {connection.message}
        </Alert>
      );
    case "CANDIDATE":
      return (
        <Stack gap="sm">
          <Group>
            <Avatar src={connection.candidate.account_avatar_url} />
            <Text fw={600}>{connection.candidate.account_login}</Text>
            <Badge color="green">{t("verified")}</Badge>
          </Group>
          <AppMetadata state={connection.app} onRetry={onRetry} />
          <Text size="sm" c="dimmed">
            {t("candidateNotice")}
          </Text>
        </Stack>
      );
    case "VERIFIED": {
      const result = connection.verification;
      return (
        <Stack gap="sm">
          {result.identity.type === "user" ? (
            <Group>
              <Avatar src={result.identity.avatar_url} />
              <Text fw={600}>{result.identity.login}</Text>
              <Badge color="green">{t("identityVerified")}</Badge>
            </Group>
          ) : (
            <Group>
              <Text fw={600}>{result.identity.name}</Text>
              <Badge variant="filled">{t("appIdentity")}</Badge>
            </Group>
          )}
          {result.installations.map((target) => (
            <Group key={target.installation_id} wrap="wrap">
              <Avatar src={target.account_avatar_url} size="sm" />
              <Text size="sm">
                {target.account_login ?? target.installation_id}
                {target.account_type != null && ` · ${target.account_type}`}
              </Text>
              <Badge color={target.status === "ready" ? "green" : "yellow"}>
                {t(
                  target.status === "ready"
                    ? "targetReady"
                    : target.status === "denied"
                      ? "targetDenied"
                      : "targetUnavailable",
                )}
              </Badge>
              {target.message != null && (
                <Text size="sm" c="dimmed">
                  {target.message}
                </Text>
              )}
            </Group>
          ))}
          <Alert
            color={
              connection.transport === "CURRENT" &&
              result.connectivity.status === "ready"
                ? "green"
                : "yellow"
            }
          >
            {t(
              connection.transport === "CHECKING"
                ? "verifying"
                : connection.transport === "ERROR"
                  ? "connectivityFailed"
                  : connection.transport === "STALE"
                    ? "transportChanged"
                    : result.connectivity.status === "ready"
                      ? "connectivityReady"
                      : "connectivityFailed",
            )}
            {connection.transport === "CURRENT" &&
              result.connectivity.message != null && (
                <Text size="sm">{result.connectivity.message}</Text>
              )}
          </Alert>
          <Text size="sm" c="dimmed">
            {t("permissionsNotice")}
          </Text>
        </Stack>
      );
    }
  }
}

export function GitHubWizard(props: GitHubWizardProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github.wizard");
  const g = useTranslations("workspace.toolkits.github");
  const f = useTranslations("workspace.toolkits");
  const userMode =
    props.mode === "github_app_user" ||
    props.mode === "github_app_platform_user";
  const selfManaged =
    props.mode === "github_app" || props.mode === "github_app_user";
  const platformMode =
    props.mode === "github_app_platform" ||
    props.mode === "github_app_platform_user";
  const locked =
    props.publication.type === "PENDING" ||
    props.publication.type === "SUCCESS" ||
    props.publication.type === "UNCERTAIN";
  const pending = props.publication.type === "PENDING";
  const shortScopeLabel =
    props.sharingScope === "personal"
      ? "personalScopeShort"
      : props.sharingScope === "agent_only"
        ? "agentScopeShort"
        : "sharedScopeShort";
  const scopeLabel =
    props.sharingScope === "personal"
      ? "personalScope"
      : props.sharingScope === "agent_only"
        ? "agentScope"
        : "sharedScope";
  const platformReadiness =
    props.availability.type === "READY"
      ? props.identity === "APP"
        ? props.availability.installation
        : props.availability.userAccount
      : null;
  const currentStep: GitHubWizardStep =
    props.identity == null
      ? "IDENTITY"
      : props.mode == null
        ? "METHOD"
        : props.stage;
  const currentIndex = GITHUB_WIZARD_STEPS.indexOf(currentStep);
  const verified =
    props.connection.type === "VERIFIED" ||
    props.connection.type === "CANDIDATE";
  function credential(
    field: keyof GitHubWizardCredentials,
    value: string | string[],
  ): void {
    props.onCredentials({ ...props.credentials, [field]: value });
  }
  function setting<K extends keyof GitHubWizardSettings>(
    field: K,
    value: GitHubWizardSettings[K],
  ): void {
    props.onSettings({ ...props.settings, [field]: value });
  }
  function selectMethod(method: "PLATFORM" | "SELF_MANAGED" | "PAT"): void {
    if (props.identity == null) {
      return;
    }
    const mode = wizardMode(props.identity, method);
    if (mode != null) {
      props.onMode(mode);
    }
  }
  function resetButton(): React.ReactElement {
    return (
      <Button
        variant="default"
        leftSection={<IconRefresh size="1em" />}
        onClick={props.onReset}
        disabled={pending}
      >
        {t("reset")}
      </Button>
    );
  }
  function nextButton(
    label: "continueFeatures" | "continueRuntime" | "continueReview",
    disabled: boolean,
  ): React.ReactElement {
    return (
      <Group justify="flex-end" mt="lg">
        <Button
          onClick={props.onContinue}
          disabled={disabled || pending}
          rightSection={<IconArrowRight size="1em" />}
        >
          {t(label)}
        </Button>
      </Group>
    );
  }
  return (
    <Container
      ref={props.rootRef}
      size="lg"
      w="100%"
      miw={0}
      px={props.embedded ? 0 : "md"}
      py={props.embedded ? 0 : "xl"}
    >
      <Stack gap="md">
        <Group align="flex-start" justify="space-between" wrap="wrap">
          <div>
            <ThemeIcon variant="default" size="xl" radius="md" aria-hidden>
              <IconBrandGithub size="1.4em" />
            </ThemeIcon>
            <Title order={3} mt="sm">
              {t("title")}
            </Title>
            <Text
              className={classes.headerSubtitle}
              size="sm"
              c="dimmed"
              mt="xs"
            >
              {t("progressiveHint")}
            </Text>
          </div>
          <Group gap="xs">
            {props.mode == null && resetButton()}
            {!props.embedded && (
              <Button
                variant="default"
                leftSection={<IconX size="1em" />}
                onClick={props.onClose}
                disabled={pending}
              >
                {t("close")}
              </Button>
            )}
          </Group>
        </Group>
        <Group gap="sm">
          <Badge
            variant="light"
            leftSection={
              props.sharingScope !== "workspace_shared" ? (
                <IconLock size="1em" />
              ) : (
                <IconUsers size="1em" />
              )
            }
          >
            {t(shortScopeLabel)}
          </Badge>
          <Text size="sm" c="dimmed">
            {t("ownershipHint")}
          </Text>
        </Group>
        <ol className={classes.progress} aria-label={t("setupProgress")}>
          {GITHUB_WIZARD_STEPS.map((step, index) => (
            <li
              key={step}
              className={classes.segment}
              data-active={index === currentIndex || void 0}
              data-complete={
                (index < currentIndex &&
                  (step !== "CONNECTION" ||
                    gitHubWizardConnectionReady(props.connection))) ||
                void 0
              }
              aria-current={index === currentIndex ? "step" : void 0}
            >
              <VisuallyHidden>{t(`progressSteps.${step}`)}</VisuallyHidden>
            </li>
          ))}
        </ol>
        <div>
          <Stack gap="md">
            <GitHubWizardSection
              disabled={locked}
              id="github-wizard-identity"
              number={1}
              title={t("identityTitle")}
              subtitle={t("identityHint")}
              complete={props.identity != null}
            >
              <SimpleGrid
                type="container"
                cols={{ base: 1, "35rem": 2 }}
                spacing="sm"
              >
                <GitHubWizardChoice
                  title={t("personalChoice")}
                  description={t("personalDescription")}
                  icon={<IconUser size="1em" />}
                  selected={props.identity === "PERSONAL"}
                  onSelect={() => props.onIdentity("PERSONAL")}
                />
                <GitHubWizardChoice
                  title={t("appChoice")}
                  description={t("appDescription")}
                  icon={<IconBrandGithub size="1em" />}
                  selected={props.identity === "APP"}
                  onSelect={() => props.onIdentity("APP")}
                />
              </SimpleGrid>
            </GitHubWizardSection>
            {props.mode == null && (
              <ConnectionEvidence
                connection={props.connection}
                onRetry={props.onRetryMetadata}
              />
            )}
            {props.identity != null && (
              <GitHubWizardSection
                disabled={locked}
                id="github-wizard-method"
                number={2}
                title={t("methodTitle")}
                subtitle={t("methodHint")}
                complete={props.mode != null}
              >
                <Stack gap="sm">
                  {props.availability.type === "LOADING" && (
                    <Group role="status">
                      <Loader size="xs" />
                      <Text size="sm">{g("availabilityLoading")}</Text>
                    </Group>
                  )}
                  {props.availability.type === "ERROR" && (
                    <Alert color="yellow">
                      <Stack gap="xs">
                        <Text>{g("availabilityError")}</Text>
                        <Button
                          onClick={props.onRetryAvailability}
                          variant="default"
                        >
                          {t("retry")}
                        </Button>
                      </Stack>
                    </Alert>
                  )}
                  {platformReadiness === "incomplete" && (
                    <Alert color="yellow">{g("platformIncomplete")}</Alert>
                  )}
                  {platformReadiness === "configured" &&
                    props.platformApp.type !== "READY" && (
                      <AppMetadata
                        state={props.platformApp}
                        onRetry={props.onRetryPlatformMetadata}
                      />
                    )}
                  <SimpleGrid
                    type="container"
                    cols={{
                      base: 1,
                      "35rem": 2,
                      "48rem": props.identity === "PERSONAL" ? 3 : 2,
                    }}
                    spacing="sm"
                  >
                    {platformReadiness === "configured" &&
                      props.platformApp.type === "READY" && (
                        <GitHubWizardChoice
                          title={t("platformMethod", {
                            name: props.platformApp.app.name,
                          })}
                          description={t("platformDescription")}
                          icon={<IconShieldCheck size="1em" />}
                          selected={platformMode}
                          onSelect={() => selectMethod("PLATFORM")}
                        />
                      )}
                    <GitHubWizardChoice
                      title={t("selfManagedMethod")}
                      description={t("selfManagedDescription")}
                      icon={<IconBrandGithub size="1em" />}
                      selected={selfManaged}
                      onSelect={() => selectMethod("SELF_MANAGED")}
                    />
                    {props.identity === "PERSONAL" && (
                      <GitHubWizardChoice
                        title={t("patMethod")}
                        description={t("patDescription")}
                        icon={<IconKey size="1em" />}
                        selected={props.mode === "pat"}
                        onSelect={() => selectMethod("PAT")}
                      />
                    )}
                  </SimpleGrid>
                  <Anchor
                    component={Link}
                    href={props.registrationGuideHref ?? "/github-app-guide"}
                    target="_blank"
                    rel="noopener noreferrer"
                    w="fit-content"
                  >
                    <Group gap="xs">
                      <IconExternalLink size="1em" />
                      <Text size="sm">{t("registrationGuide")}</Text>
                    </Group>
                  </Anchor>
                </Stack>
              </GitHubWizardSection>
            )}
            {props.mode != null && (
              <GitHubWizardSection
                disabled={locked}
                id="github-wizard-connection"
                number={3}
                title={t("connectionTitle")}
                subtitle={t("connectionHint")}
                complete={gitHubWizardConnectionReady(props.connection)}
                action={resetButton()}
              >
                <Stack gap="sm">
                  {props.connection.type !== "CANDIDATE" && (
                    <>
                      {props.mode === "pat" && (
                        <PasswordInput
                          label={g("patTokenLabel")}
                          description={g("patTokenDescription")}
                          value={props.credentials.token}
                          onChange={(event) =>
                            credential("token", event.currentTarget.value)
                          }
                        />
                      )}
                      {selfManaged && (
                        <>
                          <Anchor
                            component={Link}
                            href={
                              props.registrationGuideHref ?? "/github-app-guide"
                            }
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <Group gap="xs">
                              <IconExternalLink size="1em" />
                              <Text size="sm">{t("registrationGuide")}</Text>
                            </Group>
                          </Anchor>
                          <TextInput
                            label={g("appIdLabel")}
                            value={props.credentials.appId}
                            onChange={(event) =>
                              credential("appId", event.currentTarget.value)
                            }
                          />
                          <Textarea
                            label={g("privateKeyLabel")}
                            description={g("privateKeyDescription")}
                            autosize
                            minRows={3}
                            maxRows={6}
                            value={props.credentials.privateKey}
                            onChange={(event) =>
                              credential(
                                "privateKey",
                                event.currentTarget.value,
                              )
                            }
                          />
                        </>
                      )}
                      {props.mode === "github_app_user" && (
                        <>
                          <TextInput
                            label={g("clientIdLabel")}
                            value={props.credentials.clientId}
                            onChange={(event) =>
                              credential("clientId", event.currentTarget.value)
                            }
                          />
                          <PasswordInput
                            label={g("clientSecretLabel")}
                            value={props.credentials.clientSecret}
                            onChange={(event) =>
                              credential(
                                "clientSecret",
                                event.currentTarget.value,
                              )
                            }
                          />
                        </>
                      )}
                      {props.mode === "github_app" && (
                        <TagsInput
                          label={g("installationsLabel")}
                          description={t("installationIdsHelp")}
                          value={props.credentials.installationIds}
                          onChange={(ids) => credential("installationIds", ids)}
                        />
                      )}
                      {props.mode === "github_app_platform" && (
                        <Stack gap="sm">
                          <Group>
                            <Button
                              variant="light"
                              loading={
                                props.installationState.type === "LOADING"
                              }
                              onClick={props.onConnectInstallations}
                            >
                              {g("connectGithub")}
                            </Button>
                            <Button
                              variant="subtle"
                              onClick={props.onInstallApp}
                            >
                              {g("installNewOrg")}
                            </Button>
                          </Group>
                          {props.installationState.type === "ERROR" && (
                            <Alert color="red">
                              {g("installationLoadError")}
                            </Alert>
                          )}
                          {props.installationState.type === "READY" && (
                            <MultiSelect
                              label={g("selectInstallationLabel")}
                              data={props.installationState.installations.map(
                                (item) => ({
                                  value: String(item.id),
                                  label: `${item.account_login} · ${item.account_type}`,
                                }),
                              )}
                              value={props.credentials.installationIds}
                              onChange={(ids) =>
                                credential("installationIds", ids)
                              }
                            />
                          )}
                        </Stack>
                      )}
                      {(selfManaged || userMode) && (
                        <GitHubWizardCallbackHelp
                          availability={props.availability}
                          optional={!userMode}
                        />
                      )}
                      {userMode && (
                        <Alert color="blue">
                          <Stack gap="xs">
                            <Text size="sm">
                              {g(
                                props.mode === "github_app_user"
                                  ? "userRegistrationInstructions"
                                  : "platformUserInstructions",
                              )}
                            </Text>
                            <Anchor
                              target="_blank"
                              rel="noopener noreferrer"
                              href="https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app"
                            >
                              {g("registrationHelp")}
                            </Anchor>
                          </Stack>
                        </Alert>
                      )}
                      <Button
                        w="fit-content"
                        variant="default"
                        leftSection={<IconShieldCheck size="1em" />}
                        loading={
                          props.connection.type === "LOADING" ||
                          (props.connection.type === "VERIFIED" &&
                            props.connection.transport === "CHECKING")
                        }
                        onClick={props.onConnect}
                      >
                        {t(
                          userMode
                            ? "authorize"
                            : verified
                              ? "verifyAgain"
                              : "verify",
                        )}
                      </Button>
                    </>
                  )}

                  <ConnectionEvidence
                    connection={props.connection}
                    onRetry={props.onRetryMetadata}
                  />
                </Stack>
                {props.stage === "CONNECTION" &&
                  nextButton("continueFeatures", !props.canContinue)}
              </GitHubWizardSection>
            )}
            {props.stage !== "CONNECTION" && (
              <GitHubWizardSection
                disabled={locked}
                id="github-wizard-features"
                number={4}
                title={t("featuresTitle")}
                complete={props.stage === "RUNTIME" || props.stage === "REVIEW"}
              >
                <Stack gap="sm">
                  <Text size="sm" c="dimmed">
                    {g("toolsetsDescription")}
                  </Text>
                  <SimpleGrid
                    type="container"
                    cols={{ base: 1, "16rem": 2 }}
                    spacing="xs"
                  >
                    {GITHUB_FEATURE_GROUPS.map((group) => (
                      <div
                        key={group}
                        className={classes.feature}
                        data-selected={
                          props.settings.toolsets.includes(group) || void 0
                        }
                      >
                        <Checkbox
                          styles={{
                            body: {
                              flexDirection: "column",
                              alignItems: "flex-start",
                              gap: "var(--mantine-spacing-xs)",
                            },
                            label: { paddingInlineStart: 0 },
                          }}
                          label={t(`featureNames.${group}`)}
                          checked={props.settings.toolsets.includes(group)}
                          onChange={(event) =>
                            setting(
                              "toolsets",
                              event.currentTarget.checked
                                ? [...props.settings.toolsets, group]
                                : props.settings.toolsets.filter(
                                    (value) => value !== group,
                                  ),
                            )
                          }
                        />
                      </div>
                    ))}
                  </SimpleGrid>
                  <Text size="sm" c="dimmed">
                    {t("permissionsNotice")}
                  </Text>
                  <Accordion>
                    <Accordion.Item value="custom">
                      <Accordion.Control>
                        {t("customFeatures")}
                      </Accordion.Control>
                      <Accordion.Panel>
                        <TagsInput
                          label={g("toolsetsLabel")}
                          description={t("customFeaturesDescription")}
                          data={[...GITHUB_FEATURE_GROUPS]}
                          value={props.settings.toolsets}
                          onChange={(value) => setting("toolsets", value)}
                        />
                      </Accordion.Panel>
                    </Accordion.Item>
                  </Accordion>
                </Stack>
                {props.stage === "FEATURES" &&
                  nextButton("continueRuntime", !props.canContinue)}
              </GitHubWizardSection>
            )}
            {(props.stage === "RUNTIME" || props.stage === "REVIEW") && (
              <GitHubWizardSection
                disabled={locked}
                id="github-wizard-runtime"
                number={5}
                title={t("runtimeTitle")}
                subtitle={t("runtimeHint")}
                complete={props.stage === "REVIEW"}
              >
                <Stack gap="sm">
                  <div
                    className={classes.feature}
                    data-selected={
                      props.settings.injectRuntimeEnvironment || void 0
                    }
                  >
                    <Switch
                      label={t("runtimeToggle")}
                      description={t("runtimeHint")}
                      checked={props.settings.injectRuntimeEnvironment}
                      onChange={(event) =>
                        props.onSettings({
                          ...props.settings,
                          injectRuntimeEnvironment: event.currentTarget.checked,
                          runtimeRiskAcknowledged: false,
                        })
                      }
                    />
                  </div>
                  {props.settings.injectRuntimeEnvironment && (
                    <Alert
                      color="orange"
                      title={t("runtimeWarningTitle")}
                      styles={{
                        body: { minWidth: 0, overflowWrap: "anywhere" },
                      }}
                    >
                      <Stack gap="sm">
                        <Text size="sm">
                          {g(
                            userMode
                              ? "userRuntimeWarning"
                              : "runtimeEnvironmentWarningBody",
                          )}
                        </Text>
                        <Checkbox
                          label={t("runtimeAcknowledge")}
                          checked={props.settings.runtimeRiskAcknowledged}
                          onChange={(event) =>
                            setting(
                              "runtimeRiskAcknowledged",
                              event.currentTarget.checked,
                            )
                          }
                        />
                      </Stack>
                    </Alert>
                  )}
                </Stack>
                {props.stage === "RUNTIME" &&
                  nextButton(
                    "continueReview",
                    !props.canContinue ||
                      (props.settings.injectRuntimeEnvironment &&
                        !props.settings.runtimeRiskAcknowledged),
                  )}
              </GitHubWizardSection>
            )}
            {props.stage === "REVIEW" && (
              <GitHubWizardSection
                disabled={locked}
                id="github-wizard-review"
                number={6}
                title={t("reviewTitle")}
                subtitle={t("reviewHint")}
              >
                <Stack gap="md">
                  <TextInput
                    label={f("nameLabel")}
                    placeholder="GitHub"
                    value={props.settings.name}
                    onChange={(event) =>
                      setting("name", event.currentTarget.value)
                    }
                  />
                  <dl className={classes.summary}>
                    <dt>{t("identitySummary")}</dt>
                    <dd>
                      {props.connection.type === "CANDIDATE" ? (
                        <Group gap="xs">
                          <Text size="sm">
                            {props.connection.candidate.account_login}
                            {props.connection.app.type === "READY" &&
                              ` · ${props.connection.app.app.name}`}
                          </Text>
                        </Group>
                      ) : props.connection.type === "VERIFIED" ? (
                        <Text size="sm">
                          {props.connection.verification.identity.type ===
                          "user"
                            ? props.connection.verification.identity.login
                            : props.connection.verification.identity.name}
                          {props.connection.verification.installations.length >
                            0 &&
                            ` · ${props.connection.verification.installations.map((target) => target.account_login ?? target.installation_id).join(", ")}`}
                        </Text>
                      ) : (
                        <Text size="sm">{t("connectionError")}</Text>
                      )}
                    </dd>
                    <dt>{t("scopeSummary")}</dt>
                    <dd>{t(shortScopeLabel)}</dd>
                    <dt>{t("selectedFeaturesSummary")}</dt>
                    <dd>
                      {props.settings.toolsets.map((group) => (
                        <Badge
                          key={group}
                          variant="outline"
                          tt="none"
                          color="gray"
                          mr="xs"
                          mb="xs"
                        >
                          {isKnownGitHubFeature(group)
                            ? t(`featureNames.${group}`)
                            : group}
                        </Badge>
                      ))}
                    </dd>
                    <dt>{t("runtimeSummary")}</dt>
                    <dd>
                      {t(
                        props.settings.injectRuntimeEnvironment ? "on" : "off",
                      )}
                    </dd>
                  </dl>
                  <Accordion>
                    <Accordion.Item value="advanced">
                      <Accordion.Control>{t("advanced")}</Accordion.Control>
                      <Accordion.Panel>
                        <Stack gap="sm">
                          <TagsInput
                            label={g("toolsetsLabel")}
                            description={t("customFeaturesDescription")}
                            data={[...GITHUB_FEATURE_GROUPS]}
                            value={props.settings.toolsets}
                            onChange={(value) => setting("toolsets", value)}
                          />
                          <TextInput
                            label={f("slugLabel")}
                            description={
                              props.sharingScope === "agent_only"
                                ? f("agentSlugDescription")
                                : f("slugDescription")
                            }
                            value={props.settings.slug}
                            onChange={(event) =>
                              setting("slug", event.currentTarget.value)
                            }
                          />
                          <Textarea
                            label={f("descriptionLabel")}
                            value={props.settings.description}
                            onChange={(event) =>
                              setting("description", event.currentTarget.value)
                            }
                          />
                          <Textarea
                            label={f("customPromptLabel")}
                            description={f("customPromptDescription")}
                            value={props.settings.prompt}
                            onChange={(event) =>
                              setting("prompt", event.currentTarget.value)
                            }
                          />
                          <NumberInput
                            label={t("timeout")}
                            min={1}
                            value={props.settings.timeout}
                            onChange={(value) => {
                              if (typeof value === "number") {
                                setting("timeout", value);
                              }
                            }}
                          />
                          <Switch
                            label={f("alwaysExposeToolsLabel")}
                            description={f("alwaysExposeToolsDescription")}
                            checked={props.settings.alwaysExposeTools}
                            onChange={(event) =>
                              setting(
                                "alwaysExposeTools",
                                event.currentTarget.checked,
                              )
                            }
                          />
                          <Switch
                            label={f("enabledLabel")}
                            checked={props.settings.enabled}
                            onChange={(event) =>
                              setting("enabled", event.currentTarget.checked)
                            }
                          />
                        </Stack>
                      </Accordion.Panel>
                    </Accordion.Item>
                  </Accordion>
                  <Alert variant="light">{t(scopeLabel)}</Alert>
                  <Group justify="flex-end">
                    <Button
                      onClick={props.onPublish}
                      loading={pending}
                      disabled={
                        !props.canContinue ||
                        locked ||
                        (props.settings.injectRuntimeEnvironment &&
                          !props.settings.runtimeRiskAcknowledged)
                      }
                      rightSection={<IconArrowRight size="1em" />}
                    >
                      {t("confirm")}
                    </Button>
                  </Group>
                </Stack>
              </GitHubWizardSection>
            )}
          </Stack>
        </div>
        <div aria-live="polite" role="status">
          {props.publication.type === "ERROR" && (
            <Alert color="red">{props.publication.message}</Alert>
          )}
          {props.publication.type === "UNCERTAIN" && (
            <Alert color="yellow">
              <Stack gap="sm">
                <Text>{t("uncertain")}</Text>
                <Button variant="light" onClick={props.onInspect}>
                  {t("inspect")}
                </Button>
              </Stack>
            </Alert>
          )}
          {props.publication.type === "SUCCESS" && (
            <Alert color="green">{t("saved")}</Alert>
          )}
        </div>
      </Stack>
    </Container>
  );
}
