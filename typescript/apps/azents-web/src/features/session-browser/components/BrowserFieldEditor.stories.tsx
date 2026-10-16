import { Box, Text, Textarea } from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { useBrowserFieldEditor } from "../containers/useBrowserFieldEditor";
import { useBrowserInteraction } from "../containers/useBrowserInteraction";
import { BrowserFieldEditor } from "./BrowserFieldEditor";
import type {
  BrowserFieldAttributes,
  BrowserFieldResult,
  BrowserFrame,
} from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

const nativeAttributes: BrowserFieldAttributes = {
  input_type: "text",
  input_mode: null,
  autocomplete: "",
  autocapitalize: null,
  autocorrect: null,
  spellcheck: true,
  enter_key_hint: null,
  max_length: null,
  min_length: null,
  pattern: "",
  required: false,
  multiple: false,
  placeholder: "",
  name: "",
};

const frame: BrowserFrame = {
  type: "frame",
  attachment_id: "fixture",
  target: {
    task_id: "fixture",
    page_id: "fixture",
    resource_incarnation: "fixture",
  },
  frame_sequence: 1,
  navigation_id: "fixture",
  width: 800,
  height: 600,
  media_type: "image/jpeg",
  editables: [
    {
      id: "native-fixture",
      x: 10,
      y: 10,
      width: 200,
      height: 40,
      input_mode: "text",
    },
  ],
};

function Fixture({
  kind = "text",
  clipboardText = "Clipboard fixture",
  attributes: suppliedAttributes,
  initialValue = "Synthetic original value",
}: {
  kind?: "text" | "password" | "multiline";
  clipboardText?: string;
  attributes?: BrowserFieldAttributes;
  initialValue?: string;
}): ReactElement {
  const [remote, setRemote] = useState(initialValue);
  const attributes: BrowserFieldAttributes = suppliedAttributes ?? {
    ...nativeAttributes,
    input_type:
      kind === "multiline"
        ? "textarea"
        : kind === "password"
          ? "password"
          : "text",
  };
  const cancelInput = useRef<() => void>(() => {});
  const [enabled, setEnabled] = useState(true);
  const result = useRef<(result: BrowserFieldResult) => void>(() => {});
  const editor = useBrowserFieldEditor({
    scope: "fixture",
    enabled,
    frame,
    label: "Synthetic field",
    cancelInput: () => cancelInput.current(),
    readClipboard: () => Promise.resolve(clipboardText),
    open: () => {
      queueMicrotask(() =>
        result.current({
          type: "opened",
          field: {
            type: "field_value",
            attachment_id: "fixture",
            sequence: 1,
            editable_id: "native-fixture",
            edit_id: "fixture-edit",
            kind:
              attributes.input_type === "textarea"
                ? "multiline"
                : attributes.input_type === "password"
                  ? "password"
                  : "text",
            attributes,
            value: remote,
          },
        }),
      );
      return true;
    },
    finish: (value) => {
      if (value !== null) {
        setRemote(value);
      }
      queueMicrotask(() => result.current({ type: "completed" }));
      return true;
    },
  });
  result.current = editor.result;
  const interaction = useBrowserInteraction({
    enabled: enabled && editor.controls.draft === null,
    frame,
    onAction: (_, action) => {
      if (action.kind === "paste") {
        setRemote((value) => value + action.text);
      }
      return true;
    },
    readClipboard: () => Promise.resolve(clipboardText),
  });
  cancelInput.current = interaction.cancel;
  useEffect(() => {
    const revoke = (): void => setEnabled(false);
    window.addEventListener("fixture-revoke-field", revoke);
    return () => window.removeEventListener("fixture-revoke-field", revoke);
  }, []);
  return (
    <Box p="md">
      <Text>
        Synthetic transport fixture using the production editor lifecycle.
      </Text>
      <Textarea
        label="Remote receiver"
        data-browser-native-input="native-fixture"
        readOnly={interaction.interaction === null}
        onFocus={interaction.interaction?.onKeyboardFocus}
        onPointerDown={interaction.interaction?.onKeyboardPointerDown}
        onPaste={interaction.interaction?.onPaste}
      />
      <Text data-testid="remote-value">{remote}</Text>
      <BrowserFieldEditor
        controls={{
          ...editor.controls,
          toolbarVisible: interaction.paste.enabled,
          onDirectPaste: interaction.paste.onPaste,
        }}
      />
    </Box>
  );
}
const meta = {
  title: "Features/Session Browser/Components/BrowserFieldEditor",
  component: Fixture,
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;

export const OneShotLifecycle = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const open = async (): Promise<void> => {
      await userEvent.click(
        canvas.getByRole("textbox", { name: "Remote receiver" }),
      );
      await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
      await waitFor(() =>
        expect(
          canvas.getByRole("textbox", { name: "Synthetic field" }),
        ).toHaveFocus(),
      );
    };
    await open();
    await expect(
      canvas.getByRole("textbox", { name: "Synthetic field" }),
    ).toHaveValue("Synthetic original value");
    await userEvent.clear(
      canvas.getByRole("textbox", { name: "Synthetic field" }),
    );
    await userEvent.type(
      canvas.getByRole("textbox", { name: "Synthetic field" }),
      "Discard this edit",
    );
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(canvas.queryByRole("dialog")).toBeNull());
    await expect(canvas.getByTestId("remote-value")).toHaveTextContent(
      "Synthetic original value",
    );
    await open();
    await userEvent.clear(
      canvas.getByRole("textbox", { name: "Synthetic field" }),
    );
    await userEvent.click(canvas.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(canvas.queryByRole("dialog")).toBeNull());
    await expect(canvas.getByTestId("remote-value")).toBeEmptyDOMElement();
    await open();
    await expect(
      canvas.getByRole("textbox", { name: "Synthetic field" }),
    ).toHaveValue("");
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(canvas.queryByRole("dialog")).toBeNull());
  },
} satisfies Story;

export const PasswordSecurityInvalidation = {
  args: { kind: "password" },
  play: async ({ canvasElement }) => {
    const body = canvasElement.ownerDocument.body;
    const canvas = within(body);
    await userEvent.click(
      canvas.getByRole("textbox", { name: "Remote receiver" }),
    );
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    const password = await canvas.findByLabelText("Synthetic field");
    await expect(password).toHaveAttribute("type", "password");
    await expect(password).toHaveValue("Synthetic original value");
    canvasElement.ownerDocument.defaultView?.dispatchEvent(
      new Event("fixture-revoke-field"),
    );
    await waitFor(() =>
      expect(body.querySelector('input[type="password"]')).toBeNull(),
    );
    await expect(canvas.getByTestId("remote-value")).toHaveTextContent(
      "Synthetic original value",
    );
    await waitFor(() => expect(canvas.queryByRole("dialog")).toBeNull());
  },
} satisfies Story;

export const Multiline = { args: { kind: "multiline" } } satisfies Story;

export const OriginalEmailAttributes = {
  args: {
    initialValue: "reader@example.test",
    clipboardText: "new@example.test",
    attributes: {
      ...nativeAttributes,
      input_type: "email",
      input_mode: "email",
      autocomplete: "email",
      autocapitalize: "off",
      autocorrect: "off",
      spellcheck: false,
      enter_key_hint: "next",
      max_length: 80,
      min_length: 3,
      pattern: ".+@.+",
      required: true,
      multiple: true,
      placeholder: "name@example.test",
      name: "contact",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("textbox", { name: "Remote receiver" }),
    );
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    const input = await canvas.findByRole("textbox", {
      name: /Synthetic field/,
    });
    for (const [name, value] of Object.entries({
      type: "email",
      inputmode: "email",
      autocomplete: "email",
      autocapitalize: "off",
      autocorrect: "off",
      spellcheck: "false",
      enterkeyhint: "next",
      maxlength: "80",
      minlength: "3",
      pattern: ".+@.+",
      placeholder: "name@example.test",
      name: "contact",
    })) {
      await expect(input).toHaveAttribute(name, value);
    }
    await expect(input).toHaveAttribute("required");
    await expect(input).toHaveAttribute("multiple");
    if (!(input instanceof HTMLInputElement)) {
      throw new Error("Native input is required");
    }
    await expect(input.selectionStart).toBeNull();
    input.focus();
    input.select();
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    await waitFor(() => expect(input).toHaveValue("new@example.test"));
    await userEvent.click(canvas.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(canvas.queryByRole("dialog")).toBeNull());
    await expect(canvas.getByTestId("remote-value")).toHaveTextContent(
      "new@example.test",
    );
  },
} satisfies Story;

export const NativePasswordPaste = {
  args: { kind: "password", clipboardText: "Synthetic\r\nClipboard" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("textbox", { name: "Remote receiver" }),
    );
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    const input = await canvas.findByLabelText("Synthetic field");
    await userEvent.clear(input);
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    const expected =
      args.kind === "multiline" ? "Synthetic\nClipboard" : "SyntheticClipboard";
    await waitFor(() => expect(input).toHaveValue(expected));
    await userEvent.click(canvas.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(canvas.queryByRole("dialog")).toBeNull());
    await expect(canvas.getByTestId("remote-value").textContent).toBe(expected);
  },
} satisfies Story;

export const NativeMultilinePaste = {
  ...NativePasswordPaste,
  args: { kind: "multiline", clipboardText: "Synthetic\r\nClipboard" },
} satisfies Story;

export const LowerToolbarUsesSelectedReceiver = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const receiver = canvas.getByRole("textbox", { name: "Remote receiver" });
    await userEvent.click(receiver);
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    await waitFor(() =>
      expect(canvas.getByTestId("remote-value")).toHaveTextContent(
        "Synthetic original valueClipboard fixture",
      ),
    );
    await expect(receiver).toHaveFocus();
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    await waitFor(() =>
      expect(
        canvas.getByRole("textbox", { name: "Synthetic field" }),
      ).toHaveValue("Synthetic original valueClipboard fixture"),
    );
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(canvas.queryByRole("dialog")).toBeNull());
  },
} satisfies Story;
