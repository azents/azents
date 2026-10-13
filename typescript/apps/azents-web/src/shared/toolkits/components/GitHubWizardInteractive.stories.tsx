import { Button, Modal, rem, Stack, Text } from "@mantine/core";
import { NextIntlClientProvider, useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import frenchMessages from "@/i18n/fr-FR-messages";
import japaneseMessages from "@/i18n/ja-JP-messages";
import koreanMessages from "@/i18n/ko-KR-messages";
import { LocaleProvider } from "@/shared/providers/locale";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { useGitHubWizardProgression } from "../containers/useGitHubWizardProgression";
import { soleGitHubChoice, soleGitHubMethod } from "../github-wizard-selection";
import {
  DEFAULT_GITHUB_WIZARD_SETTINGS,
  gitHubWizardConnectionReady,
  wizardIdentity,
} from "../github-wizard-state";
import {
  wizardCandidateConnection,
  wizardStoryProps,
} from "./github-wizard-story-fixtures";
import { GitHubWizard } from "./GitHubWizard";
import type {
  GitHubWizardAvailability,
  GitHubWizardConnection,
  GitHubWizardCredentials,
  GitHubWizardIdentity,
  GitHubWizardMode,
  GitHubWizardPublication,
  GitHubWizardSettings,
} from "../github-wizard-state";
import type { GitHubWizardProps } from "./GitHubWizard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

interface PreviewProps {
  embedded?: boolean;
  installationChoices?: number[];
  availability?: GitHubWizardAvailability;
}
const emptyCredentials: GitHubWizardCredentials = {
  token: "",
  appId: "",
  privateKey: "",
  clientId: "",
  clientSecret: "",
  installationIds: [],
};

/** Safe local fixture orchestration. No provider, tRPC, navigation, or browser persistence. */
function InteractiveWizardPreview({
  embedded = false,
  installationChoices = [7],
  availability = wizardStoryProps.availability,
}: PreviewProps): ReactElement {
  const t = useTranslations("workspace.toolkits.github.wizard");
  const locale = useLocale();
  const guideStory =
    locale === "ko-KR"
      ? "korean"
      : locale === "fr-FR"
        ? "french"
        : locale === "ja-JP"
          ? "japanese"
          : "desktop";
  const progression = useGitHubWizardProgression();
  const [opened, setOpened] = useState(true);
  const [identity, setIdentity] = useState<GitHubWizardIdentity | null>(null);
  const [mode, setMode] = useState<GitHubWizardMode | null>(null);
  const [connection, setConnection] = useState<GitHubWizardConnection>({
    type: "INPUT",
  });
  const [stage, setStage] = useState<GitHubWizardProps["stage"]>("CONNECTION");
  const [settings, setSettings] = useState<GitHubWizardSettings>(
    DEFAULT_GITHUB_WIZARD_SETTINGS,
  );
  const [credentials, setCredentials] =
    useState<GitHubWizardCredentials>(emptyCredentials);
  const [publication, setPublication] = useState<GitHubWizardPublication>({
    type: "IDLE",
  });
  const [installationState, setInstallationState] = useState<
    GitHubWizardProps["installationState"]
  >({ type: "IDLE" });
  const touched = useRef(false);
  const canContinue = gitHubWizardConnectionReady(connection);
  function reset(): void {
    setConnection({ type: "INPUT" });
    setCredentials(emptyCredentials);
    setStage("CONNECTION");
    setPublication({ type: "IDLE" });
    setInstallationState({ type: "IDLE" });
    touched.current = false;
    setSettings((previous) => ({
      ...previous,
      runtimeRiskAcknowledged: false,
    }));
  }
  useEffect(() => {
    const only = soleGitHubMethod(identity, availability);
    if (mode == null && only != null) {
      setMode(only);
    }
  }, [identity, mode, availability]);
  const props: GitHubWizardProps = {
    ...wizardStoryProps,
    registrationGuideHref: `/?path=/story/toolkits-github-app-guide--${guideStory}`,
    rootRef: progression.rootRef,
    embedded,
    sharingScope: embedded ? "agent_only" : "workspace_shared",
    availability,
    identity,
    mode,
    connection,
    stage,
    settings,
    credentials,
    publication,
    installationState,
    canContinue,
    candidate: connection.type === "CANDIDATE" ? connection.candidate : null,
    onIdentity: (next) => {
      if (identity === next) {
        return;
      }
      reset();
      setIdentity(next);
      const only = soleGitHubMethod(next, availability);
      setMode(only);
      progression.advance(only == null ? "METHOD" : "CONNECTION");
    },
    onMode: (next) => {
      if (mode === next) {
        return;
      }
      reset();
      setMode(next);
      setIdentity(wizardIdentity(next));
      progression.advance("CONNECTION");
    },
    onCredentials: (next) => {
      if (
        next.installationIds.join("\0") !==
        credentials.installationIds.join("\0")
      ) {
        touched.current = true;
      }
      setCredentials(next);
      setConnection({ type: "INPUT" });
      setStage("CONNECTION");
    },
    onSettings: (next) => {
      if (
        connection.type === "VERIFIED" &&
        (next.timeout !== settings.timeout ||
          next.toolsets.join("\0") !== settings.toolsets.join("\0"))
      ) {
        setConnection({ ...connection, transport: "STALE" });
      }
      setSettings(next);
    },
    onConnect: () => {
      if (mode === "github_app_user" || mode === "github_app_platform_user") {
        setConnection({
          ...wizardCandidateConnection,
          candidate: {
            ...wizardCandidateConnection.candidate,
            source: mode === "github_app_user" ? "byoa_user" : "platform_user",
            sharing_scope: embedded ? "agent_only" : "workspace_shared",
          },
        });
      } else {
        setConnection({
          type: "VERIFIED",
          transport: "CURRENT",
          verification: {
            identity:
              mode === "pat"
                ? {
                    type: "user",
                    id: 42,
                    login: "fixture-user",
                    avatar_url: null,
                  }
                : {
                    type: "app",
                    app_id: "123",
                    name: "Azents Test App",
                    slug: "azents-test-app",
                  },
            installations:
              mode === "pat"
                ? []
                : credentials.installationIds.map((id) => ({
                    installation_id: id,
                    account_login: "fixture-org",
                    account_type: "Organization",
                    account_avatar_url: null,
                    status: "ready",
                    message: null,
                  })),
            connectivity: { status: "ready", message: null },
          },
        });
      }
    },
    onContinue: () => {
      if (!canContinue) {
        return;
      }
      const next =
        stage === "CONNECTION"
          ? "FEATURES"
          : stage === "FEATURES"
            ? "RUNTIME"
            : "REVIEW";
      setStage(next);
      progression.advance(next);
    },
    onReset: reset,
    onClose: () => {
      reset();
      if (embedded) {
        setOpened(false);
      }
    },
    onInspect: () => setPublication({ type: "IDLE" }),
    onPublish: () => {
      if (
        canContinue &&
        (!settings.injectRuntimeEnvironment || settings.runtimeRiskAcknowledged)
      ) {
        setPublication({ type: "SUCCESS" });
      }
    },
    onConnectInstallations: () => {
      const items = installationChoices.map((id) => ({
        id,
        account_login: id === 7 ? "fixture-org" : `fixture-org-${id}`,
        account_type: "Organization",
      }));
      setInstallationState({ type: "READY", installations: items });
      const only = soleGitHubChoice(
        "READY",
        items.map((item) => String(item.id)),
        touched.current,
      );
      if (only != null && credentials.installationIds.length === 0) {
        setCredentials({ ...credentials, installationIds: [only] });
      }
    },
    onInstallApp: () => {
      /* Synthetic preview performs no installation or navigation. */
    },
  };
  const wizard = <GitHubWizard {...props} />;
  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        {t("previewDescription")}
      </Text>
      {embedded ? (
        <>
          <Button variant="default" onClick={() => setOpened(true)}>
            {t("openPreview")}
          </Button>
          <Modal
            opened={opened}
            onClose={() => {
              reset();
              setOpened(false);
            }}
            title={t("previewTitle")}
            size="lg"
            centered
            closeButtonProps={{ "aria-label": t("close") }}
          >
            {wizard}
          </Modal>
        </>
      ) : (
        wizard
      )}
    </Stack>
  );
}

const meta = {
  title: "Toolkits/GitHub Wizard interactive",
  component: InteractiveWizardPreview,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(980)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof InteractiveWizardPreview>;
export default meta;
type Story = StoryObj<typeof meta>;
// Manual stories deliberately have no play function: users start at the first choice.
export const Interactive: Story = {};
export const InteractiveMobile: Story = {
  parameters: { testViewport: { width: 390, height: 844 } },
};
export const InteractiveAgentModal: Story = { args: { embedded: true } };
export const SingleMethod: Story = {
  args: {
    availability: {
      type: "READY",
      userAccount: "absent",
      installation: "absent",
      callbackUrl: null,
    },
  },
};
export const AvailabilityLoadingInteractive: Story = {
  args: { availability: { type: "LOADING" } },
};
export const KoreanInteractive: Story = {
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
        <LocaleProvider locale="ko-KR">
          <Story />
        </LocaleProvider>
      </NextIntlClientProvider>
    ),
  ],
};
export const FrenchInteractive: Story = {
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="fr-FR" messages={frenchMessages}>
        <LocaleProvider locale="fr-FR">
          <Story />
        </LocaleProvider>
      </NextIntlClientProvider>
    ),
  ],
};
export const JapaneseInteractive: Story = {
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ja-JP" messages={japaneseMessages}>
        <LocaleProvider locale="ja-JP">
          <Story />
        </LocaleProvider>
      </NextIntlClientProvider>
    ),
  ],
};

async function assertHeadingInViewport(element: HTMLElement): Promise<void> {
  await waitFor(async () => {
    await expect(element.ownerDocument.activeElement).toBe(element);
    const rect = element.getBoundingClientRect();
    const dialog = element.closest('[role="dialog"]');
    const header = dialog?.querySelector(".mantine-Modal-header");
    const top = header?.getBoundingClientRect().bottom ?? 0;
    await expect(rect.top).toBeGreaterThanOrEqual(top);
    await expect(rect.bottom).toBeLessThanOrEqual(
      element.ownerDocument.defaultView?.innerHeight ?? 0,
    );
  });
}
async function progressionPlay({
  canvasElement,
}: {
  canvasElement: HTMLElement;
}): Promise<void> {
  const body = within(canvasElement.ownerDocument.body);
  await userEvent.click(
    body.getByRole("button", { name: "Connect with my GitHub account" }),
  );
  await assertHeadingInViewport(
    body.getByRole("heading", { name: /Choose an authentication method$/ }),
  );
  await userEvent.click(
    body.getByRole("button", { name: "GitHub App · Azents Test App" }),
  );
  await assertHeadingInViewport(
    body.getByRole("heading", { name: /Verify your connection$/ }),
  );
  await userEvent.click(
    body.getByRole("button", { name: "Authorize with GitHub" }),
  );
  await userEvent.click(
    body.getByRole("button", { name: "Continue to features" }),
  );
  await assertHeadingInViewport(
    body.getByRole("heading", { name: /Choose tools to use$/ }),
  );
  await userEvent.click(
    body.getByRole("button", { name: "Continue to Runtime" }),
  );
  await assertHeadingInViewport(
    body.getByRole("heading", { name: /Runtime environment$/ }),
  );
  await userEvent.click(
    body.getByRole("button", { name: "Review connection" }),
  );
  const heading = body.getByRole("heading", { name: /Review and save$/ });
  await assertHeadingInViewport(heading);
  const name = body.getByRole("textbox", { name: "Name" });
  const before = heading.getBoundingClientRect().top;
  await userEvent.type(name, "Preview connection");
  await expect(heading.ownerDocument.activeElement).toBe(name);
  await expect(
    Math.abs(heading.getBoundingClientRect().top - before),
  ).toBeLessThan(2);
}
export const ProgressionPageQA: Story = { play: progressionPlay };
export const ProgressionMobileQA: Story = {
  ...InteractiveMobile,
  play: progressionPlay,
};
export const ProgressionAgentModalQA: Story = {
  args: { embedded: true },
  play: progressionPlay,
};
export const SingleMethodQA: Story = {
  ...SingleMethod,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /Connect with a GitHub App/ }),
    );
    await expect(
      canvas.getByRole("button", { name: "Register a GitHub App" }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      canvas.getByRole("button", { name: "Verify connection" }),
    ).toBeVisible();
    await expect(
      canvas.queryByText("Identity verified"),
    ).not.toBeInTheDocument();
    await assertHeadingInViewport(
      canvas.getByRole("heading", { name: /Verify your connection$/ }),
    );
  },
};

export const SoleInstallationQA: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect with a GitHub App" }),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "GitHub App · Azents Test App" }),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect with GitHub" }),
    );
    await expect(canvas.getByText("fixture-org · Organization")).toBeVisible();
    await expect(canvas.queryByText("Target verified")).not.toBeInTheDocument();
    const remove = canvas
      .getByText("fixture-org · Organization")
      .closest(".mantine-Pill-root")
      ?.querySelector("button");
    if (remove == null) {
      throw new Error("Selected installation remove control missing");
    }
    await userEvent.click(remove);
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect with GitHub" }),
    );
    await expect(
      canvas.queryByText("fixture-org · Organization"),
    ).not.toBeInTheDocument();
  },
};
export const MultipleInstallationsQA: Story = {
  args: { installationChoices: [7, 8] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect with a GitHub App" }),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "GitHub App · Azents Test App" }),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect with GitHub" }),
    );
    await expect(
      canvas.queryByText("fixture-org · Organization"),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByText("fixture-org-8 · Organization"),
    ).not.toBeInTheDocument();
  },
};
export const LoadingChoiceQA: Story = {
  ...AvailabilityLoadingInteractive,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect with a GitHub App" }),
    );
    await expect(
      canvas.getByRole("button", { name: "Register a GitHub App" }),
    ).toHaveAttribute("aria-pressed", "false");
    await expect(
      canvas.queryByRole("button", { name: "Verify connection" }),
    ).not.toBeInTheDocument();
  },
};
