import {
  Accordion,
  Alert,
  Anchor,
  Avatar,
  Badge,
  Button,
  Checkbox,
  Container,
  Divider,
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
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { GITHUB_FEATURE_GROUPS, wizardMode } from "../github-wizard-state";
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
  sharingScope: "workspace_shared" | "agent_only";
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
  headingRef?: RefObject<HTMLHeadingElement | null>;
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
              <Badge>{t("appIdentity")}</Badge>
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
  const platformReadiness =
    props.availability.type === "READY"
      ? props.identity === "APP"
        ? props.availability.installation
        : props.availability.userAccount
      : null;
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
  const verified =
    props.connection.type === "VERIFIED" ||
    props.connection.type === "CANDIDATE";
  return (
    <Container
      size="md"
      w="100%"
      miw={0}
      px={props.embedded ? 0 : "md"}
      py={props.embedded ? 0 : "xl"}
    >
      <Stack gap="lg">
        <Group justify="space-between" wrap="wrap">
          <Title order={3}>{t("title")}</Title>
          <Group gap="xs">
            <Button
              variant="default"
              onClick={props.onReset}
              disabled={pending}
            >
              {t("reset")}
            </Button>
            {!props.embedded && (
              <Button
                variant="default"
                onClick={props.onClose}
                disabled={pending}
              >
                {t("close")}
              </Button>
            )}
          </Group>
        </Group>
        <fieldset
          disabled={locked}
          style={{ border: 0, padding: 0, minWidth: 0 }}
        >
          <Stack gap="lg">
            <section aria-labelledby="github-wizard-identity">
              <Stack gap="sm">
                <Title id="github-wizard-identity" order={4}>
                  {t("identityTitle")}
                </Title>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <Button
                    h="auto"
                    py="md"
                    variant={
                      props.identity === "PERSONAL" ? "light" : "default"
                    }
                    aria-pressed={props.identity === "PERSONAL"}
                    onClick={() => props.onIdentity("PERSONAL")}
                    styles={{ label: { whiteSpace: "normal" } }}
                  >
                    <Stack gap="xs">
                      <Text fw={600}>{t("personalChoice")}</Text>
                      <Text size="sm" fw={400}>
                        {t("personalDescription")}
                      </Text>
                    </Stack>
                  </Button>
                  <Button
                    h="auto"
                    py="md"
                    variant={props.identity === "APP" ? "light" : "default"}
                    aria-pressed={props.identity === "APP"}
                    onClick={() => props.onIdentity("APP")}
                    styles={{ label: { whiteSpace: "normal" } }}
                  >
                    <Stack gap="xs">
                      <Text fw={600}>{t("appChoice")}</Text>
                      <Text size="sm" fw={400}>
                        {t("appDescription")}
                      </Text>
                    </Stack>
                  </Button>
                </SimpleGrid>
              </Stack>
            </section>
            {props.mode == null && (
              <ConnectionEvidence
                connection={props.connection}
                onRetry={props.onRetryMetadata}
              />
            )}
            {props.identity != null && (
              <section aria-labelledby="github-wizard-method">
                <Stack gap="sm">
                  <Divider />
                  <Title
                    id="github-wizard-method"
                    ref={props.mode == null ? props.headingRef : void 0}
                    tabIndex={-1}
                    order={4}
                  >
                    {t("methodTitle")}
                  </Title>
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
                          variant="subtle"
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
                    (props.platformApp.type === "READY" ? (
                      <Button
                        h="auto"
                        py="sm"
                        styles={{ label: { whiteSpace: "normal" } }}
                        variant={platformMode ? "light" : "default"}
                        aria-pressed={platformMode}
                        onClick={() => selectMethod("PLATFORM")}
                      >
                        {t("platformMethod", {
                          name: props.platformApp.app.name,
                        })}
                      </Button>
                    ) : (
                      <AppMetadata
                        state={props.platformApp}
                        onRetry={props.onRetryPlatformMetadata}
                      />
                    ))}
                  <Button
                    variant={selfManaged ? "light" : "default"}
                    aria-pressed={selfManaged}
                    onClick={() => selectMethod("SELF_MANAGED")}
                  >
                    {t("selfManagedMethod")}
                  </Button>
                  {props.identity === "PERSONAL" && (
                    <Button
                      variant={props.mode === "pat" ? "light" : "default"}
                      aria-pressed={props.mode === "pat"}
                      onClick={() => selectMethod("PAT")}
                    >
                      {t("patMethod")}
                    </Button>
                  )}
                </Stack>
              </section>
            )}
            {props.mode != null && (
              <section aria-labelledby="github-wizard-connection">
                <Stack gap="sm">
                  <Divider />
                  <Title
                    id="github-wizard-connection"
                    ref={
                      props.stage === "CONNECTION" ? props.headingRef : void 0
                    }
                    tabIndex={-1}
                    order={4}
                  >
                    {t("connectionTitle")}
                  </Title>
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
                            <Text size="sm">{g("callbackLabel")}</Text>
                            <Text
                              size="sm"
                              style={{ overflowWrap: "anywhere" }}
                            >
                              {props.availability.type === "READY"
                                ? (props.availability.callbackUrl ??
                                  g("callbackUnavailable"))
                                : g("availabilityLoading")}
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
                        variant="light"
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
                  {props.stage === "CONNECTION" && (
                    <Button
                      w="fit-content"
                      onClick={props.onContinue}
                      disabled={!props.canContinue}
                    >
                      {t("continueFeatures")}
                    </Button>
                  )}
                </Stack>
              </section>
            )}
            {props.stage !== "CONNECTION" && (
              <section aria-labelledby="github-wizard-features">
                <Stack gap="sm">
                  <Divider />
                  <Title
                    id="github-wizard-features"
                    ref={props.stage === "FEATURES" ? props.headingRef : void 0}
                    tabIndex={-1}
                    order={4}
                  >
                    {t("featuresTitle")}
                  </Title>
                  <TagsInput
                    label={g("toolsetsLabel")}
                    description={g("toolsetsDescription")}
                    data={GITHUB_FEATURE_GROUPS}
                    value={props.settings.toolsets}
                    onChange={(value) => setting("toolsets", value)}
                  />
                  <Text size="sm" c="dimmed">
                    {t("permissionsNotice")}
                  </Text>
                  {props.stage === "FEATURES" && (
                    <Button
                      w="fit-content"
                      onClick={props.onContinue}
                      disabled={!props.canContinue}
                    >
                      {t("continueRuntime")}
                    </Button>
                  )}
                </Stack>
              </section>
            )}
            {(props.stage === "RUNTIME" || props.stage === "REVIEW") && (
              <section aria-labelledby="github-wizard-runtime">
                <Stack gap="sm">
                  <Divider />
                  <Title
                    id="github-wizard-runtime"
                    ref={props.stage === "RUNTIME" ? props.headingRef : void 0}
                    tabIndex={-1}
                    order={4}
                  >
                    {t("runtimeTitle")}
                  </Title>
                  <Switch
                    label={g("runtimeEnvironmentToggle")}
                    description={g(
                      userMode
                        ? "userRuntimeDescription"
                        : "runtimeEnvironmentToggleDescription",
                    )}
                    checked={props.settings.injectRuntimeEnvironment}
                    onChange={(event) =>
                      props.onSettings({
                        ...props.settings,
                        injectRuntimeEnvironment: event.currentTarget.checked,
                        runtimeRiskAcknowledged: false,
                      })
                    }
                  />
                  {props.settings.injectRuntimeEnvironment && (
                    <Alert
                      color="orange"
                      title={g("runtimeEnvironmentWarningTitle")}
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
                          label={g("runtimeEnvironmentAcknowledge")}
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
                  {props.stage === "RUNTIME" && (
                    <Button
                      w="fit-content"
                      disabled={
                        !props.canContinue ||
                        (props.settings.injectRuntimeEnvironment &&
                          !props.settings.runtimeRiskAcknowledged)
                      }
                      onClick={props.onContinue}
                    >
                      {t("continueReview")}
                    </Button>
                  )}
                </Stack>
              </section>
            )}
            {props.stage === "REVIEW" && (
              <section aria-labelledby="github-wizard-review">
                <Stack gap="sm">
                  <Divider />
                  <Title
                    id="github-wizard-review"
                    ref={props.headingRef}
                    tabIndex={-1}
                    order={4}
                  >
                    {t("reviewTitle")}
                  </Title>
                  <TextInput
                    label={f("nameLabel")}
                    placeholder="GitHub"
                    value={props.settings.name}
                    onChange={(event) =>
                      setting("name", event.currentTarget.value)
                    }
                  />
                  <Accordion>
                    <Accordion.Item value="advanced">
                      <Accordion.Control>{t("advanced")}</Accordion.Control>
                      <Accordion.Panel>
                        <Stack gap="sm">
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
                  <ConnectionEvidence
                    connection={props.connection}
                    onRetry={props.onRetryMetadata}
                  />
                  <Text size="sm">
                    {t("reviewSettings", {
                      groups: props.settings.toolsets.join(", "),
                      runtime: t(
                        props.settings.injectRuntimeEnvironment ? "on" : "off",
                      ),
                    })}
                  </Text>
                  <Alert color="blue">
                    {t(
                      props.sharingScope === "agent_only"
                        ? "agentScope"
                        : "sharedScope",
                    )}
                  </Alert>
                  <Button
                    onClick={props.onPublish}
                    loading={pending}
                    disabled={
                      !props.canContinue ||
                      locked ||
                      (props.settings.injectRuntimeEnvironment &&
                        !props.settings.runtimeRiskAcknowledged)
                    }
                  >
                    {t("confirm")}
                  </Button>
                </Stack>
              </section>
            )}
          </Stack>
        </fieldset>
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
