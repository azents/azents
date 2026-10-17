import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { changeConnectionAgent, connectionAllows } from "../access-draft";
import { personalToolFixture } from "../personal-tools-fixtures";
import { PersonalAccess } from "./PersonalAccess";
import type { ConnectionAccessDraft } from "../access-draft";
import type { PersonalAccessProps, PersonalAccessState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const ready: Extract<PersonalAccessState, { type: "READY" }> = {
  type: "READY",
  subject: "Personal research connection",
  account: "researcher@example.com",
  groups: [
    {
      id: "workspace-a",
      name: "",
      items: [
        {
          id: "agent-a",
          name: "Research assistant",
          detail:
            "Researches primary sources and prepares referenced summaries.",
          avatar: {
            filename: "azents-icon-dark-tile.png",
            default: {
              url: "/brand/azents/azents-icon-dark-tile.png",
              width: 512,
              height: 512,
            },
            thumbnails: {},
            uploaded_at: "2026-10-17T00:00:00Z",
          },
          allowed: true,
        },
        {
          id: "agent-b",
          name: "Technical writer",
          detail: "Turns reviewed findings into clear technical documentation.",
          allowed: true,
        },
        {
          id: "agent-c",
          name: "Code assistant",
          detail: "Investigates code and verifies changes.",
          allowed: true,
        },
      ],
    },
  ],
  empty: false,
  mode: "all",
  firstRestriction: false,
};
const meta = {
  title: "Personal Tools/Agent Access",
  component: PersonalAccess,
  args: {
    handle: "workspace",
    state: ready,
    target: "connection",
    search: "",
    dirty: false,
    write: { type: "IDLE" },
    onSearch: fn(),
    onMode: fn(),
    onToggle: fn(),
    onSave: fn(),
    onCancel: fn(),
    onReload: fn(),
  },
} satisfies Meta<typeof PersonalAccess>;
export default meta;
type Story = StoryObj<typeof meta>;

function DraftFixture(props: PersonalAccessProps): React.ReactElement {
  const [draft, setDraft] = useState<ConnectionAccessDraft | null>(null);
  const [search, setSearch] = useState("");
  const current: ConnectionAccessDraft = draft ?? {
    baseline: personalToolFixture(),
    mode: "all",
    changes: {},
  };
  const state: PersonalAccessState = {
    ...ready,
    mode: current.mode,
    firstRestriction: current.mode === "selected",
    groups: ready.groups.map((group) => ({
      ...group,
      items: group.items
        .filter((item) =>
          item.name.toLowerCase().includes(search.toLowerCase()),
        )
        .map((item) => ({
          ...item,
          allowed: connectionAllows(current, item.id),
        })),
    })),
  };
  return (
    <PersonalAccess
      {...props}
      state={state}
      search={search}
      dirty={draft !== null}
      onSearch={setSearch}
      onMode={(mode) => setDraft({ ...current, mode, changes: {} })}
      onToggle={(id, allowed) =>
        setDraft(changeConnectionAgent(current, id, allowed))
      }
      onCancel={() => {
        props.onCancel();
        setDraft(null);
      }}
    />
  );
}

export const AllAgents: Story = {};
export const SelectedProfiles: Story = {
  render: (props) => <DraftFixture {...props} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const writer = canvas.getByRole("checkbox", { name: "Technical writer" });
    await userEvent.click(writer);
    await expect(writer).not.toBeChecked();
    const coder = canvas.getByRole("checkbox", { name: "Code assistant" });
    coder.focus();
    await userEvent.keyboard(" ");
    await expect(coder).not.toBeChecked();
    await expect(
      canvas.getByRole("checkbox", { name: "Research assistant" }),
    ).toBeChecked();
  },
};
export const SelectedProfilesMobile: Story = {
  ...SelectedProfiles,
  globals: { viewport: { value: "mobile1", isRotated: false } },
};
export const RestrictAndCancel: Story = {
  render: (props) => <DraftFixture {...props} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const agent = canvas.getByRole("checkbox", { name: "Research assistant" });
    agent.focus();
    await userEvent.keyboard(" ");
    await expect(agent).not.toBeChecked();
    await expect(
      canvas.getByRole("radio", { name: "Selected Agents" }),
    ).toBeChecked();
    await expect(
      canvas.getByText(/Saving keeps the currently accessible Agents/),
    ).toBeVisible();
    await userEvent.type(
      canvas.getByRole("textbox", { name: "Find an Agent" }),
      "Code",
    );
    await expect(
      canvas.queryByRole("checkbox", { name: "Research assistant" }),
    ).not.toBeInTheDocument();
    await userEvent.clear(
      canvas.getByRole("textbox", { name: "Find an Agent" }),
    );
    await expect(
      canvas.getByRole("checkbox", { name: "Research assistant" }),
    ).not.toBeChecked();
    await userEvent.click(
      canvas.getByRole("button", { name: "Cancel changes" }),
    );
    await expect(
      canvas.getByRole("checkbox", { name: "Research assistant" }),
    ).toBeChecked();
    await expect(args.onSave).not.toHaveBeenCalled();
  },
};
export const Selected: Story = {
  args: { state: { ...ready, mode: "selected" } },
};
export const FailedSave: Story = {
  args: { dirty: true, write: { type: "ERROR", conflict: false } },
};
export const Conflict: Story = {
  args: { dirty: true, write: { type: "ERROR", conflict: true } },
};
export const Saving: Story = {
  args: { dirty: true, write: { type: "SAVING" } },
};
export const Loading: Story = { args: { state: { type: "LOADING" } } };
export const Error: Story = { args: { state: { type: "ERROR" } } };
export const AgentEmpty: Story = {
  args: {
    target: "agent",
    state: {
      ...ready,
      empty: true,
      mode: null,
      groups: [],
      subject: "Research assistant",
    },
  },
};
export const AgentConnections: Story = {
  args: {
    target: "agent",
    state: {
      ...ready,
      subject: "Research assistant",
      mode: null,
      groups: [
        {
          id: "connections",
          name: "",
          items: [
            {
              id: "github",
              name: "Personal GitHub",
              detail: "github",
              allowed: true,
            },
            {
              id: "google",
              name: "Personal Google",
              detail: "google",
              allowed: false,
            },
          ],
        },
      ],
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("checkbox", { name: /Personal Google/ }),
    );
    await expect(args.onToggle).toHaveBeenCalledWith("google", true);
    await expect(canvas.queryByRole("radiogroup")).not.toBeInTheDocument();
  },
};
export const MobileLongNames: Story = {
  globals: { viewport: { value: "mobile1", isRotated: false } },
  parameters: { layout: "fullscreen" },
  args: {
    state: {
      ...ready,
      subject:
        "Personal connection with a very long organization and account name",
      account: "very-long-account-name-for-responsive-acceptance@example.com",
    },
  },
};

export const MobileLongSelection: Story = {
  globals: { viewport: { value: "mobile1", isRotated: false } },
  parameters: { layout: "fullscreen" },
  args: {
    dirty: true,
    state: {
      ...ready,
      mode: "selected",
      groups: [
        {
          id: "workspace",
          name: "",
          items: Array.from({ length: 100 }, (_, i) => ({
            id: `agent-${i}`,
            name: `Assistant ${i}`,
            detail: null,
            allowed: true,
          })),
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const save = canvas.getByRole("button", { name: "Save access" });
    await expect(save.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      window.innerHeight,
    );
    const last = canvas.getByRole("checkbox", { name: "Assistant 99" });
    last.scrollIntoView();
    await userEvent.click(last);
    await expect(save.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      window.innerHeight,
    );
    await expect(save.getBoundingClientRect().top).toBeGreaterThan(0);
  },
};
