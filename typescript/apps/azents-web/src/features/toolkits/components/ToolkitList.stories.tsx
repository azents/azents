import { Alert, Stack } from "@mantine/core";
import { useForm } from "@mantine/form";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import frenchMessages from "@/i18n/fr-FR-messages";
import japaneseMessages from "@/i18n/ja-JP-messages";
import koreanMessages from "@/i18n/ko-KR-messages";
import { LocaleProvider } from "@/shared/providers/locale";
import { wizardStoryProps } from "@/shared/toolkits/components/github-wizard-story-fixtures";
import { GitHubWizard } from "@/shared/toolkits/components/GitHubWizard";
import { McpConfigFields } from "@/shared/toolkits/components/McpConfigFields";
import { ToolkitForm } from "@/shared/toolkits/components/ToolkitForm";
import { projectGitHubFormRegistration } from "@/shared/toolkits/provider-config-views";
import { projectToolkitConfig } from "@/shared/toolkits/toolkit-config-projection";
import { ToolkitList } from "./ToolkitList";
import {
  previewProviders,
  previewToolkits,
} from "./workspace-toolkit-preview-fixtures";
import type { ToolkitListContainerOutput } from "../containers/useToolkitListContainer";
import type { WorkspaceToolkitEditor } from "../workspace-toolkit-management-state";
import type { ToolkitFormValues } from "@/shared/toolkits/schemas";
import type {
  ToolkitConfigResponse,
  ToolkitResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

const toolkitTypes: ToolkitResponse[] = previewProviders.map((provider) => ({
  slug: provider.type,
  name: provider.label,
  description: provider.description,
  config_schema: {},
  system_prompt: "",
}));
const storyProps: ToolkitListContainerOutput = {
  handle: "acme",
  listState: { type: "READY", configs: previewToolkits },
  catalogState: { type: "READY", toolkits: toolkitTypes },
  editor: { type: "CLOSED" },
  writeState: { type: "IDLE" },
  pending: false,
  setupPending: false,
  createPublicationPending: false,
  refreshFailed: false,
  deleteTarget: null,
  deleteState: { type: "IDLE" },
  onStartAdd: fn(),
  onConfigureType: fn(),
  onDetails: fn(),
  onEdit: fn(),
  onCloseEditor: fn(),
  onBack: fn(),
  onRetryRead: fn(),
  onSetupPendingChange: fn(),
  onCreatePublicationPendingChange: fn(),
  onCreateAbandonReady: fn(),
  onCompleteSetup: fn(),
  onDelete: fn(),
  onCancelDelete: fn(),
  onConfirmDelete: fn(),
  onToggleEnabled: fn(),
};

/** Real pure forms with static inputs; connection tests and submissions never call providers. */
function McpFormFixture({
  saved,
  onComplete,
}: {
  saved?: ToolkitConfigResponse;
  onComplete: () => void;
}): ReactElement {
  const form = useForm<ToolkitFormValues>({
    mode: "controlled",
    initialValues: {
      toolkitType: "mcp",
      name: saved?.name ?? "",
      slug: saved?.slug ?? "",
      description: saved?.description ?? "",
      prompt: saved?.prompt ?? "",
      config: saved?.config ?? {
        server_url: "",
        auth_type: "none",
        timeout: 30,
      },
      credentials: null,
      enabled: saved?.enabled ?? true,
      alwaysExposeTools: saved?.always_expose_tools ?? false,
    },
  });
  return (
    <ToolkitForm
      scope={{ handle: "acme" }}
      embedded
      toolkitTypeLocked
      formState={saved ? { type: "EDIT", config: saved } : { type: "CREATE" }}
      mutationState={{ type: "IDLE", error: null }}
      form={form}
      isEdit={saved != null}
      backPath="/w/acme/toolkits"
      toolOptions={[{ value: "mcp", label: "MCP" }]}
      currentToolSlug="mcp"
      namePlaceholder=""
      slugPlaceholder="mcp"
      nameRequired
      showOauthConnection={false}
      oauthConnectionPending={{ connect: false, disconnect: false }}
      githubRegistration={projectGitHubFormRegistration(
        null,
        form.values.config,
        null,
      )}
      configProjection={projectToolkitConfig("mcp", form.values.config)}
      onSubmit={form.onSubmit(onComplete)}
      onToolSelect={() => {}}
      onConfigChange={(value) => form.setFieldValue("config", value)}
      onCredentialsChange={(value) => form.setFieldValue("credentials", value)}
      onConnectOauth={() => {}}
      onDisconnectOauth={() => {}}
      oauthDisconnectConfirmation={false}
      onAskDisconnectOauth={() => {}}
      onDismissDisconnectOauth={() => {}}
      onCancel={onComplete}
      configurationFields={
        <McpConfigFields
          config={form.values.config}
          onConfigChange={(value) => form.setFieldValue("config", value)}
          credentials={form.values.credentials ?? null}
          onCredentialsChange={(value) =>
            form.setFieldValue("credentials", value)
          }
          hasCredentials={false}
          handle="acme"
          testState={{ type: "IDLE" }}
          onTestConnection={() => {}}
        />
      }
    />
  );
}

function InteractiveFixture(): ReactElement {
  const [toolkits, setToolkits] = useState(previewToolkits);
  const [editor, setEditor] = useState<WorkspaceToolkitEditor>({
    type: "CLOSED",
  });
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const selected =
    editor.type === "EDIT" || editor.type === "DETAIL"
      ? toolkits.find((item) => item.id === editor.toolkitId)
      : null;
  const complete = (): void =>
    setEditor(
      selected
        ? { type: "DETAIL", toolkitId: selected.id }
        : { type: "CLOSED" },
    );
  return (
    <Stack>
      <Alert color="gray">
        Synthetic component fixture only. No provider, network, storage or real
        saved changes.
      </Alert>
      <ToolkitList
        {...storyProps}
        listState={{ type: "READY", configs: toolkits }}
        editor={editor}
        deleteTarget={deleteTarget}
        onStartAdd={() => setEditor({ type: "CATALOG" })}
        onConfigureType={(toolkitType) =>
          setEditor({ type: "CREATE", toolkitType })
        }
        onDetails={(toolkitId) => setEditor({ type: "DETAIL", toolkitId })}
        onEdit={(toolkitId) => setEditor({ type: "EDIT", toolkitId })}
        onCloseEditor={() => setEditor({ type: "CLOSED" })}
        onBack={() =>
          setEditor(
            selected
              ? { type: "DETAIL", toolkitId: selected.id }
              : { type: "CATALOG" },
          )
        }
        onDelete={setDeleteTarget}
        onCancelDelete={() => setDeleteTarget(null)}
        onConfirmDelete={() => {
          setToolkits((items) =>
            items.filter((item) => item.id !== deleteTarget),
          );
          setDeleteTarget(null);
          setEditor({ type: "CLOSED" });
        }}
        onToggleEnabled={(toolkit, enabled) =>
          setToolkits((items) =>
            items.map((item) =>
              item.id === toolkit.id ? { ...item, enabled } : item,
            ),
          )
        }
        setupView={
          editor.type === "CREATE" && editor.toolkitType === "github" ? (
            <GitHubWizard
              {...wizardStoryProps}
              embedded
              sharingScope="workspace_shared"
            />
          ) : (
            <McpFormFixture saved={selected ?? void 0} onComplete={complete} />
          )
        }
      />
    </Stack>
  );
}

const meta = {
  title: "Toolkits/Workspace Toolkits",
  component: ToolkitList,
  args: storyProps,
} satisfies Meta<typeof ToolkitList>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Cards: Story = {};
export const Interactive: Story = { render: () => <InteractiveFixture /> };
export const Empty: Story = {
  args: { listState: { type: "READY", configs: [] } },
};
export const Loading: Story = { args: { listState: { type: "LOADING" } } };
export const Error: Story = {
  args: { listState: { type: "ERROR" } },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Refresh" }),
    );
    await expect(args.onRetryRead).toHaveBeenCalled();
  },
};
export const Catalog: Story = { args: { editor: { type: "CATALOG" } } };
export const CatalogLoading: Story = {
  args: { editor: { type: "CATALOG" }, catalogState: { type: "LOADING" } },
};
export const CatalogError: Story = {
  args: { editor: { type: "CATALOG" }, catalogState: { type: "ERROR" } },
};
export const Details: Story = {
  args: { editor: { type: "DETAIL", toolkitId: "engineering_github" } },
};
export const MissingDetails: Story = {
  args: { editor: { type: "DETAIL", toolkitId: "missing" } },
};
export const CreateGithub: Story = {
  args: {
    editor: { type: "CREATE", toolkitType: "github" },
    setupView: (
      <GitHubWizard
        {...wizardStoryProps}
        embedded
        sharingScope="workspace_shared"
      />
    ),
  },
};
export const CreateMcp: Story = {
  args: {
    editor: { type: "CREATE", toolkitType: "mcp" },
    setupView: <McpFormFixture onComplete={fn()} />,
  },
};
export const SavedEdit: Story = {
  args: {
    editor: { type: "EDIT", toolkitId: "production_mcp" },
    setupView: (
      <McpFormFixture
        saved={{
          workspace_id: "workspace-story",
          description: "A saved MCP connection.",
          prompt: null,
          enabled: true,
          always_expose_tools: false,
          has_credentials: false,
          oauth_connection: null,
          authorization_state: null,
          github_user_connection: null,
          created_at: "2026-10-14T00:00:00Z",
          updated_at: "2026-10-14T00:00:00Z",
          id: "production_mcp",
          toolkit_type: "mcp",
          slug: "production_mcp",
          name: "Production MCP",
          config: { server_url: "https://mcp.example", auth_type: "none" },
        }}
        onComplete={fn()}
      />
    ),
  },
};
export const WritePending: Story = {
  args: {
    ...Details.args,
    pending: true,
    writeState: { type: "PENDING", toolkitId: "engineering_github" },
  },
};
export const WriteError: Story = {
  args: {
    ...Details.args,
    writeState: {
      type: "ERROR",
      toolkitId: "engineering_github",
      message: "The saved setting could not be changed.",
    },
  },
};
export const CommittedReadFailure: Story = { args: { refreshFailed: true } };
export const DeleteConfirmation: Story = {
  args: { deleteTarget: "engineering_github" },
};
export const DeletePending: Story = {
  args: {
    deleteTarget: "engineering_github",
    deleteState: { type: "PENDING" },
  },
};
export const LocalDeleteFailure: Story = {
  args: {
    deleteTarget: "engineering_github",
    deleteState: {
      type: "ERROR",
      message:
        "The deletion request was interrupted. Check the saved Toolkit and try again.",
    },
  },
};
export const PublicationPending: Story = {
  args: { ...CreateGithub.args, createPublicationPending: true },
};
export const VerificationCloseAllowed: Story = {
  args: {
    ...CreateGithub.args,
    setupPending: true,
    createPublicationPending: false,
  },
};
export const SavedOauthPending: Story = {
  args: { ...SavedEdit.args, setupPending: true },
};
export const DarkCards: Story = { globals: { colorScheme: "dark" } };
export const DarkDetails: Story = {
  ...Details,
  globals: { colorScheme: "dark" },
};
export const Mobile: Story = {
  parameters: { testViewport: { width: 390, height: 844 } },
};
export const Korean: Story = {
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
export const French: Story = {
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
export const Japanese: Story = {
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

export const ManagementQa: Story = {
  render: () => <InteractiveFixture />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(canvasElement.ownerDocument.body);
    const github = canvas.getByRole("article", { name: "개발팀 GitHub" });
    await userEvent.click(
      within(github).getByRole("button", { name: "View details" }),
    );
    let modal = within(
      await page.findByRole("dialog", { name: "Toolkit details" }),
    );
    await waitFor(async () => {
      modal = within(page.getByRole("dialog", { name: "Toolkit details" }));
      await expect(
        modal.getByText("Repositories · Issues · Pull requests"),
      ).toBeVisible();
    });
    await expect(modal.getByText("Off", { exact: true })).toBeVisible();
    await expect(
      modal.queryByText("github_app", { exact: true }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      modal.getByRole("switch", { name: "Toolkit enabled" }),
    );
    await expect(modal.getByText("Disabled", { exact: true })).toBeVisible();
    await expect(
      modal.getByRole("switch", { name: "Toolkit enabled" }),
    ).not.toBeChecked();
    await userEvent.click(
      modal.getByRole("switch", { name: "Toolkit enabled" }),
    );
    await expect(
      modal.getByRole("switch", { name: "Toolkit enabled" }),
    ).toBeChecked();
    await userEvent.click(modal.getByRole("button", { name: "Delete" }));
    modal = within(await page.findByRole("dialog", { name: "Delete" }));
    await userEvent.click(
      modal.getByText("Cancel", { selector: ".mantine-Button-label" }),
    );
    await expect(github).toBeInTheDocument();
    modal = within(
      await page.findByRole("dialog", { name: "Toolkit details" }),
    );
    await userEvent.click(modal.getByRole("button", { name: "Delete" }));
    modal = within(await page.findByRole("dialog", { name: "Delete" }));
    await userEvent.click(modal.getByRole("button", { name: "Delete" }));
    await waitFor(async () => {
      await expect(
        canvas.queryByRole("article", { name: "개발팀 GitHub" }),
      ).not.toBeInTheDocument();
    });
    await userEvent.click(canvas.getByRole("button", { name: "Add Toolkit" }));
    modal = within(await page.findByRole("dialog", { name: "Add Toolkit" }));
    await userEvent.click(modal.getByRole("button", { name: /MCP 직접 지정/ }));
    modal = within(
      await page.findByRole("dialog", { name: "Configure Toolkit" }),
    );
    await waitFor(async () => {
      await expect(modal.getByRole("textbox", { name: "Name" })).toBeVisible();
    });
    await expect(
      modal.getByRole("textbox", { name: "Server URL" }),
    ).toBeVisible();
    await expect(
      modal.queryByRole("heading", { name: /connect to GitHub/ }),
    ).not.toBeInTheDocument();
  },
};

export const DeleteFromList: Story = {
  tags: ["ci-contract"],
  parameters: { testViewport: { width: 390, height: 844 } },
  render: () => <InteractiveFixture />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(canvasElement.ownerDocument.body);
    const card = within(canvas.getByRole("article", { name: "개발팀 GitHub" }));
    await userEvent.click(card.getByRole("button", { name: "Delete" }));
    let dialog = within(await page.findByRole("dialog", { name: "Delete" }));
    await waitFor(async () => {
      await expect(dialog.getByText("개발팀 GitHub")).toBeVisible();
    });
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await waitFor(async () => {
      await expect(page.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await expect(
      canvas.getByRole("article", { name: "개발팀 GitHub" }),
    ).toBeVisible();
    await userEvent.click(card.getByRole("button", { name: "Delete" }));
    dialog = within(await page.findByRole("dialog", { name: "Delete" }));
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(async () => {
      await expect(page.queryByRole("dialog")).not.toBeInTheDocument();
      await expect(
        canvas.queryByRole("article", { name: "개발팀 GitHub" }),
      ).not.toBeInTheDocument();
    });
    const root = canvasElement.ownerDocument.documentElement;
    await expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth);
  },
};

export const PendingQa: Story = {
  ...PublicationPending,
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    const dialog = within(
      await page.findByRole("dialog", { name: "Configure Toolkit" }),
    );
    await expect(dialog.getByRole("button", { name: "Back" })).toBeDisabled();
    await expect(
      dialog.queryByRole("button", { name: "Close" }),
    ).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await expect(args.onCloseEditor).not.toHaveBeenCalled();
  },
};

export const GeometryMobileQa: Story = {
  parameters: { testViewport: { width: 390, height: 844 } },
  play: async ({ canvasElement }) => {
    await waitFor(async () => {
      const root = canvasElement.ownerDocument.documentElement;
      await expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth);
      for (const card of canvasElement.querySelectorAll("article")) {
        const icon = card.querySelector(".mantine-ThemeIcon-root");
        const title = within(card).getByText(
          card.getAttribute("aria-label") ?? "",
          { exact: true },
        );
        if (icon == null) {
          throw new globalThis.Error("Provider icon missing");
        }
        const style = getComputedStyle(card);
        await expect(
          Math.abs(
            icon.getBoundingClientRect().left -
              card.getBoundingClientRect().left -
              Number.parseFloat(style.paddingLeft) -
              Number.parseFloat(style.borderLeftWidth),
          ),
        ).toBeLessThan(1);
        await expect(icon.getBoundingClientRect().bottom).toBeLessThanOrEqual(
          title.getBoundingClientRect().top,
        );
      }
    });
  },
};

function colorLuminance(color: string): number {
  const channels = color.match(/[\d.]+/g)?.map(Number);
  if (channels == null || channels.length !== 3) {
    throw new globalThis.Error(
      `Expected opaque computed RGB, received ${color}`,
    );
  }
  const [red, green, blue] = channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  if (red == null || green == null || blue == null) {
    throw new globalThis.Error("Computed color channels are missing");
  }
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}

async function assertWarningContrast(
  canvasElement: HTMLElement,
  scheme: "light" | "dark",
): Promise<void> {
  await waitFor(async () => {
    await expect(canvasElement.ownerDocument.documentElement).toHaveAttribute(
      "data-mantine-color-scheme",
      scheme,
    );
    const warnings = canvasElement.querySelectorAll<HTMLElement>(
      "[data-workspace-reauthorization]",
    );
    await expect(warnings).toHaveLength(2);
    for (const warning of warnings) {
      await expect(warning).toBeVisible();
      const style = getComputedStyle(warning);
      const foreground = colorLuminance(style.color);
      const background = colorLuminance(style.backgroundColor);
      await expect(
        (Math.max(foreground, background) + 0.05) /
          (Math.min(foreground, background) + 0.05),
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
}

export const WarningContrastLight: Story = {
  globals: { colorScheme: "light" },
  play: async ({ canvasElement }) => {
    await assertWarningContrast(canvasElement, "light");
  },
};

export const WarningContrastDark: Story = {
  globals: { colorScheme: "dark" },
  play: async ({ canvasElement }) => {
    await assertWarningContrast(canvasElement, "dark");
  },
};
