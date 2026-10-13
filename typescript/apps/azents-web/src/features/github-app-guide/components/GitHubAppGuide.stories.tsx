import { Container, rem } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { expect, userEvent, waitFor, within } from "storybook/test";
import frenchMessages from "@/i18n/fr-FR-messages";
import japaneseMessages from "@/i18n/ja-JP-messages";
import koreanMessages from "@/i18n/ko-KR-messages";
import { LocaleProvider } from "@/shared/providers/locale";
import { GitHubAppGuide } from "./GitHubAppGuide";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/GitHub App Guide",
  component: GitHubAppGuide,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof GitHubAppGuide>;

export default meta;
type Story = StoryObj<typeof meta>;

async function assertIconAboveTitleLayout(
  canvasElement: HTMLElement,
): Promise<void> {
  const main = within(canvasElement).getByRole("main");
  const title = main.querySelector("h1");
  const icon = title?.previousElementSibling;
  if (!(title instanceof HTMLElement) || !(icon instanceof HTMLElement)) {
    throw new Error("Guide title and icon are required.");
  }
  const left =
    main.getBoundingClientRect().left +
    parseFloat(getComputedStyle(main).paddingLeft);
  await expect(icon.getBoundingClientRect().bottom).toBeLessThanOrEqual(
    title.getBoundingClientRect().top,
  );
  await expect(title.getBoundingClientRect().left).toBeCloseTo(left, 1);

  for (const alert of main.querySelectorAll('[role="alert"]')) {
    const warningIcon = alert.querySelector("svg");
    const message = warningIcon?.nextElementSibling;
    if (warningIcon != null && message instanceof HTMLElement) {
      await expect(
        warningIcon.getBoundingClientRect().bottom,
      ).toBeLessThanOrEqual(message.getBoundingClientRect().top);
      await expect(warningIcon.getBoundingClientRect().left).toBeCloseTo(
        message.getBoundingClientRect().left,
        1,
      );
    }
  }

  for (const section of main.querySelectorAll("section[id]")) {
    const heading = section.querySelector("h2");
    const body = section.firstElementChild?.children.item(1);
    if (!(heading instanceof HTMLElement) || !(body instanceof HTMLElement)) {
      throw new Error("Guide steps require a heading and body.");
    }
    await expect(heading.textContent).toMatch(/^[1-6]\. /);
    await expect(heading.previousElementSibling).toBeNull();
    await expect(heading.getBoundingClientRect().left).toBeCloseTo(left, 1);
    await expect(body.getBoundingClientRect().left).toBeCloseTo(left, 1);
    await expect(getComputedStyle(body).paddingInlineStart).toBe("0px");
  }
}

export const Desktop: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: "Register a GitHub App for Azents" }),
    ).toBeVisible();
    const register = canvas.getByRole("link", {
      name: "Open personal GitHub App registration",
    });
    await expect(register).toHaveAttribute(
      "href",
      "https://github.com/settings/apps/new",
    );
    await expect(register).toHaveAttribute("target", "_blank");
    await expect(register).toHaveAttribute("rel", "noopener noreferrer");
    await expect(
      canvas.getByText(/App ID and Client ID are different values/),
    ).toBeVisible();
    await expect(
      canvas.getByText(
        /On the New GitHub App creation form, uncheck Expire user authorization tokens before clicking Create GitHub App/,
      ),
    ).toBeVisible();
    await expect(
      canvas.getByText(/Third-party Access, GitHub Apps → Configure/),
    ).toBeVisible();
    await expect(canvas.queryByRole("textbox")).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", {
        name: "Permissions for additional feature groups",
      }),
    );
    await waitFor(async () => {
      await expect(canvas.getByText("notifications")).toBeVisible();
    });
    await expect(
      canvas.getByText(/notification-list API does not support GitHub App/),
    ).toBeVisible();
    await expect(
      canvas.getByText(/Read & write for dispatching, rerunning or cancelling/),
    ).toBeVisible();
    await assertIconAboveTitleLayout(canvasElement);
  },
};

export const Mobile: Story = {
  decorators: [
    (Story): React.ReactElement => (
      <Container size={rem(390)} p={0}>
        <Story />
      </Container>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const guide = canvas.getByRole("main");
    await expect(guide.scrollWidth).toBeLessThanOrEqual(guide.clientWidth);
    await expect(
      canvas.getByRole("heading", {
        name: "4. Collect the values from the App settings",
      }),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", {
        name: "Permissions for additional feature groups",
      }),
    );
    await waitFor(async () => {
      await expect(canvas.getByText("projects")).toBeVisible();
    });
    await expect(guide.scrollWidth).toBeLessThanOrEqual(guide.clientWidth);
    await assertIconAboveTitleLayout(canvasElement);
  },
};

export const Korean: Story = {
  decorators: [
    (Story): React.ReactElement => (
      <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
        <LocaleProvider locale="ko-KR">
          <Story />
        </LocaleProvider>
      </NextIntlClientProvider>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", {
        name: "GitHub App 등록 가이드",
      }),
    ).toBeVisible();
    await expect(
      canvas.getByText(/OAuth Apps가 아니라 GitHub Apps/),
    ).toBeVisible();
    await expect(
      canvas.getByText(
        /GitHub App을 만드는 화면에서 Expire user authorization tokens 체크를 해제한 뒤 Create GitHub App/,
      ),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("heading", { name: /실행 주체를 확인/ }),
    ).not.toBeInTheDocument();
    await assertIconAboveTitleLayout(canvasElement);
  },
};

export const French: Story = {
  decorators: [
    (Story): React.ReactElement => (
      <NextIntlClientProvider locale="fr-FR" messages={frenchMessages}>
        <LocaleProvider locale="fr-FR">
          <Story />
        </LocaleProvider>
      </NextIntlClientProvider>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", {
        name: "Enregistrer une GitHub App pour Azents",
      }),
    ).toBeVisible();
    await expect(
      canvas.getByText(
        /Dans le formulaire New GitHub App, décochez Expire user authorization tokens avant de cliquer sur Create GitHub App/,
      ),
    ).toBeVisible();
    await expect(
      canvas.getByText(/obligatoire pour l'autorisation d'un compte personnel/),
    ).toBeVisible();
    await expect(canvas.queryByRole("textbox")).not.toBeInTheDocument();
    await assertIconAboveTitleLayout(canvasElement);
  },
};

export const Japanese: Story = {
  decorators: [
    (Story): React.ReactElement => (
      <NextIntlClientProvider locale="ja-JP" messages={japaneseMessages}>
        <LocaleProvider locale="ja-JP">
          <Story />
        </LocaleProvider>
      </NextIntlClientProvider>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", {
        name: "Azents に接続する GitHub App の登録ガイド",
      }),
    ).toBeVisible();
    await expect(
      canvas.getByText(
        /GitHub App の作成画面で Expire user authorization tokens のチェックを外してから、Create GitHub App/,
      ),
    ).toBeVisible();
    await expect(canvas.getByText(/個人アカウント認証では必須/)).toBeVisible();
    await expect(canvas.queryByRole("textbox")).not.toBeInTheDocument();
    await assertIconAboveTitleLayout(canvasElement);
  },
};
