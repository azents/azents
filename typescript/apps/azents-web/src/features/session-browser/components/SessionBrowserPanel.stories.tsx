import { Box, Button, rem } from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  expect,
  fireEvent,
  fn,
  userEvent,
  waitFor,
  within,
} from "storybook/test";
import { BrowserConnection, emptyBrowserLiveState } from "../connection";
import { useBrowserAddressSelection } from "../containers/useBrowserAddressSelection";
import { useBrowserEditorViewport } from "../containers/useBrowserEditorViewport";
import { useBrowserFieldVisibility } from "../containers/useBrowserFieldVisibility";
import { useBrowserInteraction } from "../containers/useBrowserInteraction";
import { useBrowserManualKeyboard } from "../containers/useBrowserManualKeyboard";
import { useBrowserTouchView } from "../containers/useBrowserTouchView";
import { browserDialogInput, browserFrameMatchesStatus } from "../input";
import { SessionBrowserPanel } from "./SessionBrowserPanel";
import type {
  BrowserFieldAttributes,
  BrowserFrame,
  BrowserInput,
  BrowserInputAction,
  BrowserPageChoice,
  BrowserStatus,
  BrowserViewState,
} from "../types";
import type { BrowserFieldEditorDraft } from "./BrowserFieldEditor";
import type { SessionBrowserPanelProps } from "./SessionBrowserPanel";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

const fieldAttributes: BrowserFieldAttributes = {
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

const target = {
  task_id: "synthetic-task",
  page_id: "synthetic-page",
  resource_incarnation: "synthetic-incarnation",
};
const page: BrowserPageChoice = {
  target,
  taskLabel: "Review delivery",
  title: "Synthetic order",
  url: "https://example.test/order",
};
const frame: BrowserFrame = {
  type: "frame",
  attachment_id: "synthetic-attachment",
  target,
  frame_sequence: 1,
  navigation_id: "synthetic-navigation",
  width: 800,
  height: 900,
  media_type: "image/jpeg",
  editables: [],
};
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="900" viewBox="0 0 800 900"><rect width="800" height="900" fill="white"/><text x="56" y="82" font-family="sans-serif" font-size="20" fill="#64748b">PARTNER PORTAL · SYNTHETIC FIXTURE</text><text x="56" y="170" font-family="sans-serif" font-size="42" fill="#1e293b">Review your delivery</text><text x="56" y="224" font-family="sans-serif" font-size="22" fill="#64748b">Sign in to view the details of your order.</text><text x="56" y="258" font-family="sans-serif" font-size="22" fill="#64748b">Static fixture. Do not enter real credentials.</text><text x="56" y="342" font-family="sans-serif" font-size="22" fill="#334155">Email address</text><rect x="56" y="366" width="688" height="76" rx="8" fill="white" stroke="#cbd5e1"/><text x="78" y="413" font-family="sans-serif" font-size="22" fill="#64748b">name@example.test</text><text x="56" y="505" font-family="sans-serif" font-size="22" fill="#334155">Password</text><rect x="56" y="530" width="688" height="76" rx="8" fill="white" stroke="#cbd5e1"/><text x="78" y="577" font-family="sans-serif" font-size="22" fill="#94a3b8">Enter your password</text><rect x="56" y="654" width="688" height="78" rx="8" fill="#345e85"/><text x="400" y="703" text-anchor="middle" font-family="sans-serif" font-size="25" fill="white">Sign in</text><text x="56" y="820" font-family="sans-serif" font-size="20" fill="#64748b">Session browser · Example page</text></svg>`;
const ready: Extract<BrowserViewState, { type: "READY" }> = {
  type: "READY",
  pages: [page],
  selected: page,
  connection: "connected",
  image: { url: `data:image/svg+xml,${encodeURIComponent(svg)}`, frame },
  status: {
    type: "status",
    attachment_id: frame.attachment_id,
    target,
    state: "connected",
    allow_input: true,
    viewport: { width: frame.width, height: frame.height },
    navigation_id: frame.navigation_id,
    dialog: null,
    conflict: false,
    opened_target: null,
  },
  canInput: true,
  canClose: true,
  dialog: null,
  conflict: false,
  outcomeUnknown: false,
};

const actions = fn(
  (frame: BrowserFrame, action: BrowserInputAction): boolean =>
    frame.width > 0 && action.kind.length > 0,
);
const cleanupMessages = fn((message: string): void => {
  JSON.parse(message);
});

function FreshAckCleanupFixture(props: SessionBrowserPanelProps): ReactElement {
  const [live, setLive] = useState(emptyBrowserLiveState);
  const [connection] = useState(
    () =>
      new BrowserConnection(
        target,
        (message) => {
          cleanupMessages(message);
          return true;
        },
        {
          create: () => `data:image/svg+xml,${encodeURIComponent(svg)}`,
          revoke: () => {},
        },
        setLive,
        () => {},
      ),
  );
  const displayFrame = useCallback(
    (sequence: number): void => {
      const header = new TextEncoder().encode(
        JSON.stringify({
          ...frame,
          frame_sequence: sequence,
        }),
      );
      const bytes = new Uint8Array(4 + header.length + 4);
      new DataView(bytes.buffer).setUint32(0, header.length);
      bytes.set(header, 4);
      bytes.set([255, 216, 255, 217], 4 + header.length);
      connection.receiveFrame(bytes.buffer);
      const image = connection.snapshot().image;
      if (image !== null) {
        connection.displayed(image);
      }
    },
    [connection],
  );
  useEffect(() => {
    connection.receiveText(JSON.stringify(ready.status));
    displayFrame(1);
    return () => connection.dispose();
  }, [connection, displayFrame]);
  const interaction = useBrowserInteraction({
    readClipboard: null,
    enabled: live.connection === "connected",
    frame: live.displayed,
    onAction: (source, action) => connection.coordinate(source, action),
  });
  return (
    <Box h={rem(800)} w="100%" maw={rem(640)}>
      <Button onClick={() => displayFrame(2)}>Acknowledge fresh frame</Button>
      <SessionBrowserPanel
        {...props}
        state={{ ...ready, image: live.image, status: live.status }}
        interaction={interaction.interaction}
        keyboardRef={interaction.keyboardRef}
      />
    </Box>
  );
}
const dialogMessages = fn(
  (input: BrowserInput): boolean => input.source === null,
);
const promptDialog = {
  id: "dialog",
  type: "prompt",
  message: "Enter synthetic delivery note",
};
const initialDialogStatus: BrowserStatus = {
  type: "status",
  attachment_id: frame.attachment_id,
  target,
  state: "connected",
  allow_input: true,
  viewport: { width: frame.width, height: frame.height },
  navigation_id: "new-navigation",
  dialog: promptDialog,
  conflict: false,
  opened_target: null,
};
async function clickBrowserViewport(surface: HTMLElement): Promise<void> {
  const modal = surface.closest('[role="dialog"]');
  if (modal !== null) {
    await waitFor(() =>
      expect(modal.contains(surface.ownerDocument.activeElement)).toBe(true),
    );
  }
  const bounds = surface.getBoundingClientRect();
  await userEvent.pointer({
    target: surface,
    keys: "[MouseLeft]",
    coords: {
      clientX: bounds.left + bounds.width / 2,
      clientY: bounds.top + bounds.height / 2,
    },
  });
}

function BrowserFixture(
  props: SessionBrowserPanelProps & {
    reportActions?: boolean;
    recordActions?: boolean;
    readClipboard?: (() => Promise<string>) | null;
    onInputAction?: (action: BrowserInputAction) => void;
  },
): ReactElement {
  const addressSelection = useBrowserAddressSelection();
  const [focused, setFocused] = useState(props.focused);
  const [zoom, setZoom] = useState(props.zoom);
  const [counts, setCounts] = useState({
    down: 0,
    move: 0,
    up: 0,
    cancel: 0,
    wheel: 0,
    text: 0,
  });
  const onAction = (
    source: BrowserFrame,
    action: BrowserInputAction,
  ): boolean => {
    props.onInputAction?.(action);
    if (props.reportActions) {
      if (action.kind === "pointer") {
        const phase = action.phase;
        setCounts((value) => ({ ...value, [phase]: value[phase] + 1 }));
      } else if (action.kind === "wheel") {
        setCounts((value) => ({ ...value, wheel: value.wheel + 1 }));
      } else if (action.kind === "composition" && action.phase === "commit") {
        setCounts((value) => ({ ...value, text: value.text + 1 }));
      }
    }
    return props.recordActions === false ? true : actions(source, action);
  };
  const active =
    props.state.type === "READY" &&
    props.state.connection === "connected" &&
    props.state.canInput &&
    props.state.image !== null &&
    props.state.status !== null &&
    props.state.status.allow_input &&
    browserFrameMatchesStatus(props.state.image.frame, props.state.status) &&
    props.state.dialog === null;
  const interaction = useBrowserInteraction({
    readClipboard: props.readClipboard ?? null,
    enabled: active && focused,
    frame:
      props.state.type === "READY" ? (props.state.image?.frame ?? null) : null,
    onAction,
  });
  const manualKeyboard = useBrowserManualKeyboard({
    enabled: active && focused && props.fieldEditor?.draft == null,
    scope: JSON.stringify(
      props.state.type === "READY"
        ? [
            props.state.selected.target,
            props.state.image?.frame.attachment_id,
            props.state.image?.frame.navigation_id,
          ]
        : props.state.type,
    ),
    cancelInput: interaction.cancel,
  });
  const touchView = useBrowserTouchView({
    enabled:
      focused &&
      props.state.type === "READY" &&
      props.state.connection === "connected" &&
      props.state.image !== null &&
      props.state.status !== null &&
      browserFrameMatchesStatus(props.state.image.frame, props.state.status) &&
      props.state.dialog === null,
    canInput: active,
    pendingInputs: 0,
    interrupted: false,
    frame:
      props.state.type === "READY" ? (props.state.image?.frame ?? null) : null,
    zoom,
    onZoomChange: setZoom,
    onAction,
    keyboardRef: interaction.keyboardRef,
    cancelInput: interaction.cancel,
  });
  useBrowserFieldVisibility({
    enabled:
      focused &&
      props.fieldEditor !== null &&
      props.fieldEditor.toolbarVisible &&
      props.fieldEditor.draft === null,
    viewport: props.fieldEditor?.viewport ?? null,
    viewWindowRef: touchView.viewWindowRef,
  });
  return (
    <Box h={rem(800)} w="100%" maw={rem(640)}>
      <SessionBrowserPanel
        {...props}
        interaction={interaction.interaction}
        keyboardRef={interaction.keyboardRef}
        manualKeyboard={manualKeyboard}
        touchView={touchView}
        addressSelection={addressSelection}
        paste={interaction.paste}
        focused={focused}
        zoom={zoom}
        onToggleFocus={() => {
          interaction.cancel();
          setFocused((value) => !value);
          props.onToggleFocus();
        }}
        onZoomChange={(value) => {
          interaction.cancel();
          touchView.cancel();
          setZoom(value);
          props.onZoomChange(value);
        }}
        onDialogResponse={(accept) => {
          if (props.state.type !== "READY" || props.state.status === null) {
            return;
          }
          const input = browserDialogInput(
            props.state.status,
            1,
            accept,
            props.dialogText || null,
          );
          if (input !== null) {
            dialogMessages(input);
            props.onDialogResponse(accept);
          }
        }}
      />
      {props.reportActions && (
        <output
          data-browser-gesture-probe
          data-zoom={zoom}
          data-focused={focused}
          data-down={counts.down}
          data-move={counts.move}
          data-up={counts.up}
          data-cancel={counts.cancel}
          data-wheel={counts.wheel}
          data-text={counts.text}
          hidden
        />
      )}
    </Box>
  );
}

function ManualKeyboardFixture(props: SessionBrowserPanelProps): ReactElement {
  const [change, setChange] = useState("initial");
  useEffect(() => {
    const handlers = [
      "navigation",
      "attachment",
      "target",
      "frame",
      "readonly",
      "disconnect",
      "dialog",
      "stale",
    ].map((kind) => {
      const listener = (): void => setChange(kind);
      window.addEventListener(`fixture-keyboard-${kind}`, listener);
      return (): void =>
        window.removeEventListener(`fixture-keyboard-${kind}`, listener);
    });
    return () => handlers.forEach((remove) => remove());
  }, []);
  const currentTarget =
    change === "target" ? { ...target, page_id: "next-page" } : target;
  const currentPage = { ...page, target: currentTarget };
  const currentFrame: BrowserFrame = {
    ...frame,
    target: currentTarget,
    frame_sequence: change === "frame" ? 2 : 1,
    navigation_id:
      change === "navigation" ? "next-document" : frame.navigation_id,
    attachment_id:
      change === "attachment" ? "next-attachment" : frame.attachment_id,
  };
  const dialog = change === "dialog" ? promptDialog : null;
  if (ready.image === null || ready.status === null) {
    throw new Error(
      "Manual keyboard fixture requires the ready image and status",
    );
  }
  return (
    <BrowserFixture
      {...props}
      state={{
        ...ready,
        connection: change === "disconnect" ? "connecting" : "connected",
        pages: [currentPage],
        selected: currentPage,
        canInput: change !== "readonly",
        dialog,
        image: { ...ready.image, frame: currentFrame },
        status: {
          ...ready.status,
          attachment_id: currentFrame.attachment_id,
          target: currentTarget,
          navigation_id:
            change === "stale" ? "other-document" : currentFrame.navigation_id,
          allow_input: change !== "readonly",
          dialog,
        },
      }}
    />
  );
}

function StreamingImageFixture(props: SessionBrowserPanelProps): ReactElement {
  const [sequence, setSequence] = useState(1);
  const current = {
    ...ready,
    image: {
      url: `data:image/svg+xml,${encodeURIComponent(svg.replace("</svg>", `<metadata>${sequence}</metadata></svg>`))}`,
      frame: { ...frame, frame_sequence: sequence },
    },
  };
  return (
    <>
      <Button onClick={() => setSequence((value) => value + 1)}>
        Receive next frame
      </Button>
      <BrowserFixture {...props} state={current} />
    </>
  );
}

function NativeReceiverFixture(props: SessionBrowserPanelProps): ReactElement {
  const [sequence, setSequence] = useState(1);
  const nativeFrame: BrowserFrame = {
    ...frame,
    frame_sequence: sequence,
    editables: [
      {
        id: "native-main",
        x: 56,
        y: 366,
        width: 688,
        height: 76,
        input_mode: "email",
      },
    ],
  };
  return (
    <>
      <Button onClick={() => setSequence((value) => value + 1)}>
        Receive native frame
      </Button>
      <BrowserFixture
        {...props}
        state={{
          ...ready,
          image: {
            frame: nativeFrame,
            url: `data:image/svg+xml,${encodeURIComponent(svg.replace("</svg>", `<metadata>${sequence}</metadata></svg>`))}`,
          },
        }}
      />
    </>
  );
}

/** Preview-only composition: synthetic paste, no clipboard or product API access. */
function PastePreviewFixture(
  props: SessionBrowserPanelProps & {
    readClipboard?: (() => Promise<string>) | null;
  },
): ReactElement {
  const [pasted, setPasted] = useState<"email" | "password" | null>(null);
  const editableFrame: BrowserFrame = {
    ...frame,
    editables: [
      {
        id: "preview-email",
        x: 56,
        y: 366,
        width: 688,
        height: 76,
        input_mode: "email",
      },
      {
        id: "preview-password",
        x: 56,
        y: 530,
        width: 688,
        height: 76,
        input_mode: "text",
      },
    ],
  };
  const content = svg
    .replace("Review your delivery", "Paste interaction preview")
    .replace(
      "Static fixture. Do not enter real credentials.",
      "Synthetic clipboard only. No device clipboard access.",
    )
    .replace(
      "name@example.test",
      pasted === "email" ? "demo@example.test" : "name@example.test",
    )
    .replace(
      "Enter your password",
      pasted === "password" ? "••••••••••••" : "Enter your password",
    );
  return (
    <>
      <BrowserFixture
        {...props}
        readClipboard={
          "readClipboard" in props
            ? (props.readClipboard ?? null)
            : () => Promise.resolve("Synthetic paste only")
        }
        onInputAction={(action) => {
          if (action.kind === "paste") {
            setPasted(
              action.editable_id === "preview-email" ? "email" : "password",
            );
          }
        }}
        state={{
          ...ready,
          selected: {
            ...page,
            taskLabel: "붙여넣기 시안 · 기기 클립보드 접근 없음",
          },
          image: {
            url: `data:image/svg+xml,${encodeURIComponent(content)}`,
            frame: editableFrame,
          },
        }}
      />
    </>
  );
}

/** Synthetic remote values and paste text; never read the device clipboard. */
function FieldEditorPreviewFixture(
  props: SessionBrowserPanelProps & {
    multiline?: boolean;
    toolbarAppearance?: "bar" | "floating";
  },
): ReactElement {
  const [selected, setSelected] = useState<"search" | "password" | null>(null);
  const [directActive, setDirectActive] = useState(false);
  const [searchValue, setSearchValue] = useState(
    props.multiline
      ? "오늘 날씨를 확인합니다.\n明日の予定\n明天的天气"
      : "서울 날씨",
  );
  const [passwordValue, setPasswordValue] = useState("SyntheticPasswordOnly");
  const [draft, setDraft] = useState<
    | (BrowserFieldEditorDraft & {
        field: "search" | "password";
      })
    | null
  >(null);
  const latestDraft = useRef(draft);
  latestDraft.current = draft;
  const editorViewport = useBrowserEditorViewport(
    draft !== null || directActive,
  );
  useEffect(() => {
    const select = (event: globalThis.PointerEvent): void => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const id = event.target.getAttribute("data-browser-native-input");
      if (id === "editor-search" || id === "editor-password") {
        setSelected(id === "editor-search" ? "search" : "password");
      }
    };
    const focus = (event: FocusEvent): void => {
      const id =
        event.target instanceof Element
          ? event.target.getAttribute("data-browser-native-input")
          : null;
      setDirectActive(id === "editor-search" || id === "editor-password");
    };
    const blur = (): void => setDirectActive(false);
    document.addEventListener("pointerdown", select, true);
    document.addEventListener("focusin", focus, true);
    document.addEventListener("focusout", blur, true);
    return () => {
      document.removeEventListener("pointerdown", select, true);
      document.removeEventListener("focusin", focus, true);
      document.removeEventListener("focusout", blur, true);
    };
  }, []);
  const editableFrame: BrowserFrame = {
    ...frame,
    editables: [
      {
        id: "editor-search",
        x: 56,
        y: 366,
        width: 688,
        height: 76,
        input_mode: "text",
      },
      {
        id: "editor-password",
        x: 56,
        y: 530,
        width: 688,
        height: 76,
        input_mode: "text",
      },
    ],
  };
  const displayText = searchValue
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\n", " ");
  const content = svg
    .replace("Review your delivery", "One-field edit preview")
    .replace(
      "Static fixture. Do not enter real credentials.",
      "Synthetic page only. No remote field access.",
    )
    .replace("Email address", props.multiline ? "Notes" : "Search query")
    .replace("name@example.test", displayText)
    .replace("Enter your password", passwordValue ? "••••••••••••" : "")
    .replace("Sign in", "Search");
  return (
    <BrowserFixture
      {...props}
      recordActions={false}
      onInputAction={(action) => {
        if (action.kind !== "wheel") {
          return;
        }
        const surface = document.querySelector<HTMLElement>(
          '[aria-label="Remote browser page"]',
        );
        const view = surface?.parentElement;
        if (surface !== null && view != null) {
          const scale = surface.getBoundingClientRect().width / frame.width;
          view.scrollTop += action.delta_y * scale;
          view.scrollLeft += action.delta_x * scale;
        }
      }}
      focusViewport={
        editorViewport === null
          ? null
          : {
              top: editorViewport.top,
              height: editorViewport.height,
            }
      }
      state={{
        ...ready,
        selected: {
          ...page,
          title: "Synthetic search",
          taskLabel: "입력창 편집 시안 · 실제 페이지 연결 없음",
        },
        image: {
          url: `data:image/svg+xml,${encodeURIComponent(content)}`,
          frame: editableFrame,
        },
      }}
      fieldEditor={{
        enabled: selected !== null,
        draft,
        viewport: editorViewport,
        toolbarVisible: directActive,
        toolbarAppearance: props.toolbarAppearance ?? "bar",
        onOpen: () => {
          if (selected === null) {
            return;
          }
          setDraft({
            field: selected,
            attributes: {
              ...fieldAttributes,
              input_type:
                selected === "password"
                  ? "password"
                  : props.multiline
                    ? "textarea"
                    : "text",
            },
            label:
              selected === "password"
                ? "비밀번호"
                : props.multiline
                  ? "메모"
                  : "검색어",
            kind:
              selected === "password"
                ? "password"
                : props.multiline
                  ? "multiline"
                  : "text",
            value: selected === "password" ? passwordValue : searchValue,
          });
        },
        onChange: (value) =>
          setDraft((current) =>
            current === null ? null : { ...current, value },
          ),
        onConfirm: () => {
          if (draft === null) {
            return;
          }
          if (draft.field === "search") {
            setSearchValue(draft.value);
          } else {
            setPasswordValue(draft.value);
          }
          setDraft(null);
        },
        onCancel: () => {
          setDraft(null);
        },
        onDirectPaste: () => {
          const receiver = document.activeElement;
          if (
            selected === null ||
            !(receiver instanceof HTMLTextAreaElement) ||
            receiver.getAttribute("data-browser-native-input") !==
              `editor-${selected}`
          ) {
            return;
          }
          const field = selected;
          const originalValue =
            field === "search" ? searchValue : passwordValue;
          void Promise.resolve("Synthetic paste only").then(
            (text) => {
              if (
                document.activeElement !== receiver ||
                !receiver.isConnected
              ) {
                return;
              }
              if (text.length === 0) {
                return;
              }
              if (originalValue.length + text.length > 32768) {
                return;
              }
              const update = (value: string): string =>
                value !== originalValue ? value : value + text;
              if (field === "search") {
                setSearchValue(update);
              } else {
                setPasswordValue(update);
              }
            },
            () => {},
          );
        },
        onPaste: (insertNative) => {
          if (draft === null) {
            return;
          }
          const original = draft;
          void Promise.resolve("Synthetic paste only").then(
            (text) => {
              if (
                latestDraft.current !== original ||
                [...text].length > 32768
              ) {
                return;
              }
              const value = insertNative(text);
              if (value === null) {
                return;
              }
              setDraft((current) =>
                current !== original
                  ? current
                  : {
                      ...current,
                      value,
                    },
              );
            },
            () => {},
          );
        },
      }}
    />
  );
}

const meta = {
  component: SessionBrowserPanel,
  parameters: { layout: "fullscreen" },
  render: (props) => <BrowserFixture {...props} />,
  args: {
    readOnly: false,
    focused: true,
    focusViewport: null,
    zoom: 1,
    onToggleFocus: fn(),
    onZoomChange: fn(),
    state: ready,
    addressValue: page.url,
    addressSelection: null,
    addressError: false,
    navigationEnabled: true,
    onAddressChange: fn(),
    onAddressFocus: fn(),
    onAddressBlur: fn(),
    onAddressSubmit: fn(),
    onNavigate: fn(),
    closeError: false,
    createError: false,
    canCreate: true,
    creating: false,
    onCreatePage: fn(),
    onSelect: fn(),
    onClosePage: fn(),
    onRetry: fn(),
    onFrameDisplayed: fn(),
    onFrameError: fn(),
    onDialogResponse: fn(),
    dialogText: "",
    onDialogTextChange: fn(),
    keyboardRef: null,
    manualKeyboard: null,
    interaction: null,
    touchView: null,
    paste: null,
    fieldEditor: null,
  },
  beforeEach: (): void => {
    actions.mockClear();
    dialogMessages.mockClear();
  },
} satisfies Meta<typeof SessionBrowserPanel>;
export default meta;
type Story = StoryObj<typeof meta>;

export const DeletingReadOnly: Story = {
  tags: ["ci-contract"],
  args: { readOnly: true, focused: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "New tab" }),
    ).toBeDisabled();
  },
};

export const ManualKeyboardWithoutRecognizedInput = {
  render: (props) => <ManualKeyboardFixture {...props} />,
  play: async ({ canvasElement }) => {
    const body = canvasElement.ownerDocument.body;
    const canvas = within(body);
    const button = canvas.getByRole("button", { name: "Show keyboard" });
    const receiver = body.querySelector(
      "textarea:not([data-browser-native-input])",
    );
    if (!(receiver instanceof HTMLTextAreaElement)) {
      throw new Error("Missing generic native keyboard receiver");
    }
    await expect(
      body.querySelectorAll("[data-browser-native-input]"),
    ).toHaveLength(0);
    await expect(receiver).toHaveAttribute("inputmode", "none");
    // First-open remote Tab must still restore the generic keyboard stop.
    for (const name of ["Send Tab", "Send Shift+Tab"]) {
      await userEvent.click(
        canvas.getByRole("button", { name: "Browser actions" }),
      );
      await userEvent.click(canvas.getByRole("menuitem", { name }));
      await expect(receiver).toHaveFocus();
      await expect(receiver).toHaveAttribute("inputmode", "none");
    }
    actions.mockClear();
    await userEvent.click(button);
    await expect(receiver).toHaveFocus();
    await expect(receiver).toHaveAttribute("inputmode", "text");
    await expect(actions).not.toHaveBeenCalled();
    window.dispatchEvent(new Event("fixture-keyboard-frame"));
    await waitFor(() => expect(receiver).toHaveFocus());
    await expect(receiver).toHaveAttribute("inputmode", "text");
    await userEvent.type(receiver, "Manual", { skipClick: true });
    const committed = actions.mock.calls
      .flatMap(([, action]) =>
        action.kind === "composition" && action.phase === "commit"
          ? [action.text]
          : [],
      )
      .join("");
    await expect(committed).toBe("Manual");
    await expect(actions.mock.calls[0]?.[0].frame_sequence).toBe(2);
    await expect(
      actions.mock.calls.every(
        ([, action]) => action.kind !== "paste" && action.kind !== "pointer",
      ),
    ).toBe(true);
    await expect(receiver).toHaveValue("");
    await userEvent.click(
      canvas.getByRole("textbox", { name: "Browser address" }),
    );
    await expect(receiver).toHaveAttribute("inputmode", "none");
    for (const kind of ["navigation", "attachment", "target"]) {
      await userEvent.click(button);
      await expect(receiver).toHaveFocus();
      window.dispatchEvent(new Event(`fixture-keyboard-${kind}`));
      await waitFor(() =>
        expect(receiver).toHaveAttribute("inputmode", "none"),
      );
      await expect(receiver).not.toHaveFocus();
    }
  },
} satisfies Story;

export const ManualKeyboardAfterNativeSelection = {
  render: (props) => <NativeReceiverFixture {...props} />,
  play: async ({ canvasElement }) => {
    const body = canvasElement.ownerDocument.body;
    const canvas = within(body);
    const native = body.querySelector(
      '[data-browser-native-input="native-main"]',
    );
    const generic = body.querySelector(
      "textarea:not([data-browser-native-input])",
    );
    if (
      !(native instanceof HTMLTextAreaElement) ||
      !(generic instanceof HTMLTextAreaElement)
    ) {
      throw new Error("Native and generic fixture receivers are required");
    }
    await userEvent.click(native);
    await expect(native).toHaveFocus();
    actions.mockClear();
    await userEvent.click(
      canvas.getByRole("button", { name: "Show keyboard" }),
    );
    await expect(generic).toHaveFocus();
    await expect(generic).toHaveAttribute("inputmode", "text");
    await expect(native).not.toHaveFocus();
    await expect(actions).not.toHaveBeenCalled();
    await expect(canvas.getByRole("button", { name: "Paste" })).toBeDisabled();
    await expect(
      canvas.queryByRole("dialog", { name: "Edit input" }),
    ).toBeNull();
  },
} satisfies Story;

export const ManualKeyboardAuthorityLoss = {
  render: (props) => <ManualKeyboardFixture {...props} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const button = canvas.getByRole("button", { name: "Show keyboard" });
    const receiver = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    for (const kind of ["readonly", "disconnect", "dialog", "stale"]) {
      window.dispatchEvent(new Event("fixture-keyboard-navigation"));
      await waitFor(() => expect(button).toBeEnabled());
      await userEvent.click(button);
      await expect(receiver).toHaveFocus();
      window.dispatchEvent(new Event(`fixture-keyboard-${kind}`));
      await waitFor(() => expect(button).toBeDisabled());
      await expect(receiver).toHaveAttribute("inputmode", "none");
      await expect(receiver).not.toHaveFocus();
    }
  },
} satisfies Story;

export const PasteButtonPreview = {
  render: (props) => <PastePreviewFixture {...props} />,
  parameters: { viewport: { defaultViewport: "mobile1" } },
} satisfies Story;

export const FieldEditorPreview = {
  render: (props) => <FieldEditorPreviewFixture {...props} />,
  parameters: { viewport: { defaultViewport: "mobile1" } },
} satisfies Story;

export const FieldEditorMultilinePreview = {
  ...FieldEditorPreview,
  render: (props) => <FieldEditorPreviewFixture {...props} multiline />,
} satisfies Story;

export const FieldEditorFloatingPreview = {
  ...FieldEditorPreview,
  render: (props) => (
    <FieldEditorPreviewFixture {...props} toolbarAppearance="floating" />
  ),
} satisfies Story;

export const FieldEditorLowerInputVisibility = {
  ...FieldEditorPreview,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const field =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="editor-password"]',
      );
    if (field === null) {
      throw new Error("The synthetic lower input is required");
    }
    await userEvent.click(field);
    const toolbar = canvas.getByRole("toolbar", { name: "Browser actions" });
    await waitFor(async () => {
      const bounds = field.getBoundingClientRect();
      const view = field.parentElement?.parentElement?.getBoundingClientRect();
      if (!view) {
        throw new Error("The synthetic viewing area is required");
      }
      await expect(bounds.top).toBeGreaterThanOrEqual(view.top);
      await expect(bounds.bottom).toBeLessThanOrEqual(
        toolbar.getBoundingClientRect().top - 11,
      );
    });
    await expect(field).toHaveFocus();
    await expect(
      canvas.queryByRole("dialog", { name: "Edit input" }),
    ).toBeNull();
  },
} satisfies Story;

export const FieldEditorFloatingLowerInputVisibility = {
  ...FieldEditorLowerInputVisibility,
  render: (props) => (
    <FieldEditorPreviewFixture {...props} toolbarAppearance="floating" />
  ),
} satisfies Story;

export const FieldEditorPreviewInteraction = {
  ...FieldEditorPreview,
  tags: ["ci-contract"],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const open = (): HTMLElement =>
      canvas.getByRole("button", { name: "Edit" });
    await expect(
      canvas.queryByRole("button", { name: "Edit selected input" }),
    ).toBeNull();
    await expect(canvas.queryByRole("button", { name: "Paste" })).toBeNull();
    const search =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="editor-search"]',
      );
    if (search === null) {
      throw new Error("Synthetic editable target is required");
    }
    await userEvent.click(search);
    await expect(
      canvas.queryByRole("dialog", { name: "Edit input" }),
    ).toBeNull();
    const toolbar = canvas.getByRole("toolbar", { name: "Browser actions" });
    await expect(toolbar.querySelector("input,textarea")).toBeNull();
    await expect(within(toolbar).getAllByRole("button")).toHaveLength(2);
    await userEvent.click(
      within(toolbar).getByRole("button", { name: "Edit" }),
    );
    await waitFor(() =>
      expect(canvas.getByRole("dialog", { name: "Edit input" })).toBeVisible(),
    );
    const input = canvas.getByRole("textbox", { name: "검색어" });
    await expect(input).toHaveValue("서울 날씨");
    await waitFor(() => expect(input).toHaveFocus());
    const panel = canvas.getByRole("dialog", { name: "Edit input" });
    await waitFor(async () => {
      const viewport = canvasElement.ownerDocument.defaultView?.visualViewport;
      if (!viewport) {
        throw new Error("A visual viewport is required for this story");
      }
      const bounds = panel.getBoundingClientRect();
      await expect(
        Math.abs(bounds.bottom - viewport.offsetTop - viewport.height),
      ).toBeLessThan(1);
      await expect(Math.abs(bounds.height - viewport.height)).toBeLessThan(1);
    });
    await userEvent.clear(input);
    await userEvent.type(input, "오늘 날씨");
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(canvas.queryByRole("dialog", { name: "Edit input" })).toBeNull(),
    );
    await userEvent.click(search);
    await userEvent.click(open());
    await expect(canvas.getByRole("textbox", { name: "검색어" })).toHaveValue(
      "서울 날씨",
    );
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    await expect(canvas.getByRole("textbox", { name: "검색어" })).toHaveValue(
      "서울 날씨Synthetic paste only",
    );
    await userEvent.clear(canvas.getByRole("textbox", { name: "검색어" }));
    await userEvent.type(
      canvas.getByRole("textbox", { name: "검색어" }),
      "오늘 날씨",
    );
    await userEvent.click(canvas.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(canvas.queryByRole("dialog", { name: "Edit input" })).toBeNull(),
    );
    await userEvent.click(search);
    await expect(
      canvas.queryByRole("dialog", { name: "Edit input" }),
    ).toBeNull();
    await userEvent.click(open());
    await expect(canvas.getByRole("textbox", { name: "검색어" })).toHaveValue(
      "오늘 날씨",
    );
  },
} satisfies Story;

export const PasteButtonPreviewInteraction = {
  ...PasteButtonPreview,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      await canvas.findByRole("button", { name: "Paste" }),
    ).toBeDisabled();
    const field =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="preview-password"]',
      );
    if (field === null) {
      throw new Error("The synthetic password target is required");
    }
    await userEvent.click(field);
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    await expect(
      canvas.getByText("Text sent to the selected input."),
    ).toBeVisible();
    await expect(actions).toHaveBeenLastCalledWith(expect.anything(), {
      kind: "paste",
      editable_id: "preview-password",
      text: "Synthetic paste only",
    });
  },
} satisfies Story;

export const NativePaste = {
  ...PasteButtonPreview,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const field =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="preview-password"]',
      );
    if (field === null) {
      throw new Error("The synthetic password receiver is required");
    }
    await userEvent.click(field);
    actions.mockClear();
    await fireEvent.keyDown(field, { key: "v", ctrlKey: true });
    const clipboard = new DataTransfer();
    clipboard.setData("text/plain", "  Synthetic 한글 🔑  ");
    await fireEvent.paste(field, { clipboardData: clipboard });
    await expect(
      canvas.getByText("Text sent to the selected input."),
    ).toBeVisible();
    await expect(actions).toHaveBeenCalledTimes(1);
    await expect(actions).toHaveBeenLastCalledWith(expect.anything(), {
      kind: "paste",
      editable_id: "preview-password",
      text: "  Synthetic 한글 🔑  ",
    });
    await expect(field).toHaveValue("");
  },
} satisfies Story;

export const ClipboardDenied = {
  ...PasteButtonPreview,
  render: (props) => (
    <PastePreviewFixture
      {...props}
      readClipboard={() =>
        Promise.reject(new DOMException("Denied", "NotAllowedError"))
      }
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const field =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="preview-password"]',
      );
    if (field === null) {
      throw new Error("The synthetic input is required");
    }
    await userEvent.click(field);
    actions.mockClear();
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    await expect(
      await canvas.findByText(/Clipboard access was cancelled or denied/),
    ).toBeVisible();
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;

export const ClipboardUnavailable = {
  ...PasteButtonPreview,
  render: (props) => <PastePreviewFixture {...props} readClipboard={null} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const field =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="preview-password"]',
      );
    if (field === null) {
      throw new Error("The synthetic input is required");
    }
    await userEvent.click(field);
    actions.mockClear();
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    await expect(
      await canvas.findByText(/clipboard access is unavailable here/),
    ).toBeVisible();
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;

export const OversizedPaste = {
  ...PasteButtonPreview,
  render: (props) => (
    <PastePreviewFixture
      {...props}
      readClipboard={() => Promise.resolve("界".repeat(24000))}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const field =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="preview-password"]',
      );
    if (field === null) {
      throw new Error("The synthetic input is required");
    }
    await userEvent.click(field);
    actions.mockClear();
    await userEvent.click(canvas.getByRole("button", { name: "Paste" }));
    await expect(
      await canvas.findByText(/exceeds the paste size limit/),
    ).toBeVisible();
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;

const pendingClipboard: { resolve: ((text: string) => void) | null } = {
  resolve: null,
};
const delayedRead = fn(
  (): Promise<string> =>
    new Promise((resolve) => {
      pendingClipboard.resolve = resolve;
    }),
);
export const DelayedPasteDoesNotFollowFocus = {
  ...PasteButtonPreview,
  render: (props) => (
    <PastePreviewFixture {...props} readClipboard={delayedRead} />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    delayedRead.mockClear();
    await expect(delayedRead).not.toHaveBeenCalled();
    const field =
      canvasElement.ownerDocument.querySelector<HTMLTextAreaElement>(
        '[data-browser-native-input="preview-password"]',
      );
    if (field === null) {
      throw new Error("The synthetic input is required");
    }
    await userEvent.click(field);
    actions.mockClear();
    const button = canvas.getByRole("button", { name: "Paste" });
    await userEvent.click(button);
    await userEvent.click(button);
    await expect(delayedRead).toHaveBeenCalledTimes(1);
    const address = canvas.getByRole("textbox", { name: "Browser address" });
    await userEvent.click(address);
    if (pendingClipboard.resolve === null) {
      throw new Error("The clipboard read must be pending");
    }
    pendingClipboard.resolve("Synthetic delayed value");
    await waitFor(() => expect(button).toBeDisabled());
    await expect(actions).not.toHaveBeenCalled();
    await expect(field).toHaveValue("");
  },
} satisfies Story;

export const NativeReceiverPreservesFocus = {
  render: (props) => <NativeReceiverFixture {...props} />,
  play: async ({ canvasElement }) => {
    const document = canvasElement.ownerDocument;
    const canvas = within(document.body);
    const receiver = document.querySelector<HTMLTextAreaElement>(
      '[data-browser-native-input="native-main"]',
    );
    if (receiver === null) {
      throw new Error("Native receiver is required");
    }
    await userEvent.click(receiver);
    await expect(receiver).toHaveFocus();
    const blurred = fn();
    receiver.addEventListener("blur", blurred);
    await fireEvent.click(
      canvas.getByRole("button", { name: "Receive native frame" }),
    );
    await expect(
      document.querySelector('[data-browser-native-input="native-main"]'),
    ).toBe(receiver);
    await expect(receiver).toHaveFocus();
    await expect(blurred).not.toHaveBeenCalled();
    // Clear transfer intent without changing the receiver's retained DOM focus.
    await fireEvent(window, new Event("pagehide"));
    const paste = canvas.getByRole("button", { name: "Paste" });
    await expect(paste).toBeDisabled();
    const rect = receiver.getBoundingClientRect();
    const touch = {
      pointerType: "touch",
      pointerId: 17,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
    };
    await fireEvent.pointerDown(receiver, touch);
    await fireEvent.pointerUp(receiver, touch);
    await expect(paste).toBeEnabled();
    await expect(receiver).toHaveFocus();
    await expect(blurred).not.toHaveBeenCalled();
    await expect(await fireEvent.contextMenu(receiver)).toBe(true);
    const region = canvas.getByRole("region", { name: "Remote browser page" });
    await expect(await fireEvent.contextMenu(region)).toBe(false);
    const bounds = region.getBoundingClientRect();
    const outside = {
      ...touch,
      pointerId: 18,
      clientX: bounds.left + 10,
      clientY: bounds.top + 10,
    };
    await fireEvent.pointerDown(region, outside);
    await expect(receiver).toHaveFocus();
    await fireEvent.pointerMove(region, {
      ...outside,
      clientY: outside.clientY + 40,
    });
    await fireEvent.pointerUp(region, {
      ...outside,
      clientY: outside.clientY + 40,
    });
    await expect(receiver).toHaveFocus();
    await expect(blurred).not.toHaveBeenCalled();
    await expect(
      actions.mock.calls.some(([, action]) => action.kind === "wheel"),
    ).toBe(true);
    await fireEvent.pointerDown(region, { ...outside, pointerId: 19 });
    await fireEvent.pointerUp(region, { ...outside, pointerId: 19 });
    await expect(receiver).not.toHaveFocus();
    await expect(paste).toBeDisabled();
  },
} satisfies Story;

export const FreshAckPointerCleanup = {
  render: (props) => <FreshAckCleanupFixture {...props} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const region = canvas.getByRole("region", { name: "Remote browser page" });
    await waitFor(() => expect(canvas.getByRole("img")).toBeVisible());
    cleanupMessages.mockClear();
    const bounds = region.getBoundingClientRect();
    await fireEvent.pointerDown(region, {
      pointerId: 1,
      button: 0,
      clientX: bounds.left + bounds.width / 2,
      clientY: bounds.top + bounds.height / 2,
    });
    await fireEvent.click(
      canvas.getByRole("button", { name: "Acknowledge fresh frame" }),
    );
    await fireEvent(window, new Event("blur"));
    const messages: unknown[] = cleanupMessages.mock.calls
      .filter(([message]) => message.includes('"type":"input"'))
      .map(([message]): unknown => JSON.parse(message));
    await expect(messages).toMatchObject([
      {
        action: { kind: "pointer", phase: "down" },
        source: { frame_sequence: 1 },
      },
      {
        action: { kind: "pointer", phase: "cancel" },
        source: { frame_sequence: 2 },
      },
    ]);
  },
} satisfies Story;

export const FreshAckCompositionCleanup = {
  render: (props) => <FreshAckCleanupFixture {...props} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    cleanupMessages.mockClear();
    await fireEvent.compositionStart(keyboard);
    await fireEvent.click(
      canvas.getByRole("button", { name: "Acknowledge fresh frame" }),
    );
    await fireEvent(window, new Event("blur"));
    const messages: unknown[] = cleanupMessages.mock.calls
      .filter(([message]) => message.includes('"type":"input"'))
      .map(([message]): unknown => JSON.parse(message));
    await expect(messages).toMatchObject([
      {
        action: { kind: "composition", phase: "start" },
        source: { frame_sequence: 1 },
      },
      {
        action: { kind: "composition", phase: "cancel" },
        source: { frame_sequence: 2 },
      },
    ]);
  },
} satisfies Story;

export const StreamingImagePreservesFocus = {
  render: (props) => <StreamingImageFixture {...props} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await waitFor(() =>
      expect(
        canvas.getByRole("button", { name: "Exit focused view" }),
      ).toHaveFocus(),
    );
    const image = canvas.getByRole("img");
    const initialUrl = image.getAttribute("src");
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    keyboard.focus();
    await expect(keyboard).toHaveFocus();
    await fireEvent.click(
      canvas.getByRole("button", { name: "Receive next frame" }),
    );
    await waitFor(() =>
      expect(canvas.getByRole("img").getAttribute("src")).not.toBe(initialUrl),
    );
    await expect(canvas.getByRole("img")).toBe(image);
    await expect(keyboard).toHaveFocus();
    actions.mockClear();
    await userEvent.keyboard("Stable text");
    await expect(actions).toHaveBeenLastCalledWith(
      { ...frame, frame_sequence: 2 },
      { kind: "composition", phase: "commit", text: "t" },
    );
  },
} satisfies Story;

export const Focused = {
  args: { focused: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const focused = canvas.getByRole("dialog", { name: "Focus browser" });
    await expect(focused).toBeVisible();
    const bounds = focused.getBoundingClientRect();
    await expect(bounds.width).toBe(window.innerWidth);
    await expect(bounds.height).toBe(window.innerHeight);
    await userEvent.click(
      canvas.getByRole("button", { name: "Exit focused view" }),
    );
    await expect(args.onToggleFocus).toHaveBeenCalled();
  },
} satisfies Story;

export const Zoomed = {
  args: { focused: true, zoom: 2 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const viewport = canvas.getByRole("region", {
      name: "Remote browser page",
    });
    const window = viewport.parentElement;
    await expect(window).not.toBeNull();
    if (window === null) {
      throw new Error("Browser window missing");
    }
    await expect(viewport.getBoundingClientRect().width).toBe(
      window.clientWidth * 2,
    );
    await expect(window.scrollWidth).toBeGreaterThan(window.clientWidth);
  },
} satisfies Story;

export const FocusedMobile = {
  args: { focused: true },
  parameters: { viewport: { defaultViewport: "mobile1" } },
} satisfies Story;

export const FocusedLandscapePageMobile = {
  args: {
    focused: true,
    state: {
      ...ready,
      image: {
        url: `data:image/svg+xml,${encodeURIComponent(svg.replaceAll('width="800"', 'width="1280"').replaceAll('height="900"', 'height="800"').replace('viewBox="0 0 800 900"', 'viewBox="0 0 1280 800"'))}`,
        frame: { ...frame, width: 1280, height: 800 },
      },
      status:
        ready.status === null
          ? null
          : { ...ready.status, viewport: { width: 1280, height: 800 } },
    },
  },
  parameters: { viewport: { defaultViewport: "mobile1" } },
} satisfies Story;

export const Connected = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByRole("img", { name: "Browser page: Synthetic order" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("region", { name: "Remote browser page" }),
    ).toHaveAttribute("data-input", "true");
    await expect(
      canvas.getByRole("button", { name: "Close tab: Synthetic order" }),
    ).toBeEnabled();
  },
} satisfies Story;

export const PreviewOpensFocusOnly = {
  args: { focused: false },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.queryByRole("textbox", { name: "Remote browser keyboard" }),
    ).toBeNull();
    const region = canvas.getByRole("region", { name: "Remote browser page" });
    await expect(region).toHaveAttribute("data-input", "false");
    await userEvent.click(
      within(region).getByRole("button", { name: "Focus browser" }),
    );
    await expect(args.onToggleFocus).toHaveBeenCalledTimes(1);
    await expect(actions).not.toHaveBeenCalled();
    await expect(
      canvas.getByRole("dialog", { name: "Focus browser" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("textbox", { name: "Remote browser keyboard" }),
    ).toBeVisible();
  },
} satisfies Story;

export const MobileTouchGestures = {
  args: { focused: false },
  render: (props) => <BrowserFixture {...props} reportActions />,
  parameters: { viewport: { defaultViewport: "mobile1" } },
} satisfies Story;

export const MobileReadOnlyTouchGestures = {
  args: {
    state: { ...ready, canInput: false, canClose: false },
    canCreate: false,
    navigationEnabled: false,
  },
  render: (props) => <BrowserFixture {...props} reportActions />,
  parameters: { viewport: { defaultViewport: "mobile1" } },
} satisfies Story;

async function enableDirectTouch(
  canvasElement: HTMLElement,
): Promise<HTMLElement> {
  const canvas = within(canvasElement.ownerDocument.body);
  await userEvent.click(
    canvas.getByRole("button", { name: "Browser actions" }),
  );
  await userEvent.click(
    await canvas.findByRole("menuitem", { name: "Enable direct touch" }),
  );
  await expect(
    canvas.getByRole("button", { name: "Direct touch active — turn off" }),
  ).toBeVisible();
  const surface = canvas.getByRole("region", { name: "Remote browser page" });
  // Synthetic component events do not establish native pointer capture.
  surface.setPointerCapture = fn();
  surface.hasPointerCapture = (): boolean => false;
  return surface;
}

export const MobileDirectTouchHoldAndDrag = {
  tags: ["ci-contract"],
  render: (props) => <BrowserFixture {...props} />,
  parameters: { viewport: { defaultViewport: "mobile1" } },
  play: async ({ canvasElement }) => {
    const surface = await enableDirectTouch(canvasElement);
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    keyboard.focus({ preventScroll: true });
    await expect(keyboard).toHaveFocus();
    const rect = surface.getBoundingClientRect();
    const start = {
      pointerType: "touch",
      pointerId: 41,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
    };
    actions.mockClear();
    await fireEvent.pointerDown(surface, start);
    await waitFor(() =>
      expect(actions).toHaveBeenLastCalledWith(
        frame,
        expect.objectContaining({
          kind: "pointer",
          phase: "down",
          button: "left",
        }),
      ),
    );
    await expect(actions).toHaveBeenCalledTimes(1);
    await expect(keyboard).toHaveFocus();
    await expect(
      canvas.getByRole("button", { name: "Touch held — release" }),
    ).toBeVisible();
    await fireEvent.pointerMove(surface, {
      ...start,
      clientX: start.clientX + 12,
    });
    await expect(actions).toHaveBeenLastCalledWith(
      frame,
      expect.objectContaining({ kind: "pointer", phase: "move" }),
    );
    await fireEvent.pointerUp(surface, {
      ...start,
      clientX: start.clientX + 12,
    });
    await expect(actions).toHaveBeenLastCalledWith(
      frame,
      expect.objectContaining({ kind: "pointer", phase: "up" }),
    );
    await expect(actions).toHaveBeenCalledTimes(3);
    await expect(keyboard).not.toHaveFocus();

    keyboard.focus({ preventScroll: true });
    actions.mockClear();
    await fireEvent.pointerDown(surface, start);
    await fireEvent.pointerDown(surface, { ...start, pointerId: 42 });
    await expect(keyboard).toHaveFocus();
    await expect(actions).toHaveBeenLastCalledWith(
      frame,
      expect.objectContaining({ kind: "pointer", phase: "cancel" }),
    );
    await fireEvent.pointerMove(surface, { ...start, pointerId: 42 });
    await fireEvent.pointerUp(surface, { ...start, pointerId: 42 });
    await fireEvent.pointerUp(surface, start);
    await expect(actions).toHaveBeenCalledTimes(2);

    for (const reason of ["outside", "capture", "cancel", "release"] as const) {
      actions.mockClear();
      await fireEvent.pointerDown(surface, start);
      if (reason === "outside") {
        await fireEvent.pointerMove(surface, {
          ...start,
          clientX: rect.left - 1,
        });
      } else if (reason === "capture") {
        await fireEvent.lostPointerCapture(surface, start);
      } else if (reason === "cancel") {
        await fireEvent.pointerCancel(surface, start);
      } else {
        await userEvent.click(
          canvas.getByRole("button", { name: "Touch held — release" }),
        );
      }
      await expect(actions).toHaveBeenLastCalledWith(
        frame,
        expect.objectContaining({ kind: "pointer", phase: "cancel" }),
      );
      if (reason === "capture") {
        await fireEvent.pointerUp(window, start);
      } else {
        await fireEvent.pointerUp(surface, start);
      }
      await expect(actions).toHaveBeenCalledTimes(2);
    }
    actions.mockClear();
    await fireEvent.pointerDown(surface, start);
    await fireEvent(window, new Event("blur"));
    await expect(actions).toHaveBeenLastCalledWith(
      frame,
      expect.objectContaining({ kind: "pointer", phase: "cancel" }),
    );
    await expect(
      canvas.queryByRole("button", { name: "Direct touch active — turn off" }),
    ).toBeNull();
  },
} satisfies Story;

function DirectTouchScopeFixture(
  props: SessionBrowserPanelProps,
): ReactElement {
  const [current, setCurrent] = useState(ready);
  const image = ready.image;
  if (image === null) {
    throw new Error("The scope fixture requires an initial image");
  }
  const updateFrame = (navigation: string, sequence: number): void => {
    setCurrent({
      ...ready,
      image: {
        url: image.url,
        frame: {
          ...frame,
          navigation_id: navigation,
          frame_sequence: sequence,
        },
      },
      status:
        ready.status === null
          ? null
          : { ...ready.status, navigation_id: navigation },
    });
  };
  return (
    <>
      <Button onClick={() => updateFrame(frame.navigation_id, 8)}>
        Advance displayed frame
      </Button>
      <Button onClick={() => updateFrame("next-document", 9)}>
        Change native document
      </Button>
      <Button onClick={() => setCurrent({ ...current, connection: "stale" })}>
        Disconnect fixture
      </Button>
      <BrowserFixture {...props} state={current} />
    </>
  );
}

export const MobileDirectTouchSourceLifetime = {
  tags: ["ci-contract"],
  render: (props) => <DirectTouchScopeFixture {...props} />,
  play: async ({ canvasElement }) => {
    const surface = await enableDirectTouch(canvasElement);
    const canvas = within(canvasElement.ownerDocument.body);
    const rect = surface.getBoundingClientRect();
    const start = {
      pointerType: "touch",
      pointerId: 21,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
    };
    actions.mockClear();
    await fireEvent.pointerDown(surface, start);
    // Fixture controls change source metadata; they are not part of the modal UI.
    await fireEvent.click(
      canvas.getByRole("button", { name: "Advance displayed frame" }),
    );
    await expect(
      canvas.getByRole("button", { name: "Touch held — release" }),
    ).toBeVisible();
    await fireEvent.pointerUp(surface, start);
    await expect(actions).toHaveBeenLastCalledWith(
      { ...frame, frame_sequence: 8 },
      expect.objectContaining({ kind: "pointer", phase: "up" }),
    );
    await fireEvent.pointerDown(surface, start);
    await fireEvent.click(
      canvas.getByRole("button", { name: "Change native document" }),
    );
    await expect(actions).toHaveBeenLastCalledWith(
      { ...frame, frame_sequence: 8 },
      expect.objectContaining({ kind: "pointer", phase: "cancel" }),
    );
    await expect(
      canvas.queryByRole("button", { name: "Direct touch active — turn off" }),
    ).toBeNull();
    await fireEvent.pointerUp(surface, start);
    await enableDirectTouch(canvasElement);
    await fireEvent.pointerDown(surface, start);
    await fireEvent.click(
      canvas.getByRole("button", { name: "Disconnect fixture" }),
    );
    await expect(actions).toHaveBeenLastCalledWith(
      { ...frame, navigation_id: "next-document", frame_sequence: 9 },
      expect.objectContaining({ kind: "pointer", phase: "cancel" }),
    );
    await expect(
      canvas.queryByRole("button", { name: "Direct touch active — turn off" }),
    ).toBeNull();
  },
} satisfies Story;

export const MobileDirectTouchReadOnly = {
  tags: ["ci-contract"],
  args: {
    state: { ...ready, canInput: false, canClose: false },
    canCreate: false,
    navigationEnabled: false,
  },
  render: (props) => <BrowserFixture {...props} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("button", { name: "Browser actions" }),
    );
    await expect(
      await canvas.findByRole("menuitem", { name: "Enable direct touch" }),
    ).toHaveAttribute("data-disabled", "true");
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;

export const MobileDirectTouchSending = {
  tags: ["ci-contract"],
  render: (props) => <SessionBrowserPanel {...props} />,
  args: {
    touchView: {
      frame,
      direct: {
        active: true,
        pressed: true,
        sending: true,
        available: false,
        onToggle: fn(),
        onRelease: fn(),
      },
      cancel: fn(),
      viewWindowRef: { current: null },
      touch: {
        onPointerDown: fn(),
        onPointerMove: fn(),
        onPointerUp: fn(),
        onPointerCancel: fn(),
        onLostPointerCapture: fn(),
      },
      touchFeedback: null,
      onTouchFeedbackEnd: fn(),
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("button", { name: "Sending touch — release" }),
    );
    await expect(args.touchView?.direct.onRelease).toHaveBeenCalledTimes(1);
  },
} satisfies Story;

export const BrowserTabs = {
  args: {
    state: {
      ...ready,
      pages: [
        page,
        {
          ...page,
          target: { ...target, page_id: "second" },
          title: "Another tab",
        },
      ],
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("button", { name: "Close tab: Another tab" }),
    );
    await expect(args.onClosePage).toHaveBeenCalledWith({
      ...target,
      page_id: "second",
    });
    await expect(args.onSelect).not.toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "New tab" }));
    await expect(args.onCreatePage).toHaveBeenCalledTimes(1);
    await expect(
      canvas.getByRole("button", { name: "Exit focused view" }),
    ).toBeVisible();
  },
} satisfies Story;

export const AddressSelectsAllOnEntry = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const address = canvas.getByRole("textbox", { name: "Browser address" });
    await userEvent.click(address);
    await expect(canvasElement.ownerDocument.getSelection()?.toString()).toBe(
      page.url,
    );
    await userEvent.keyboard("{Backspace}");
    await expect(args.onAddressChange).toHaveBeenLastCalledWith("");
  },
} satisfies Story;

export const AddressKeepsLaterCaretEdits = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const address = canvasElement.ownerDocument.querySelector<HTMLInputElement>(
      'input[aria-label="Browser address"]',
    );
    if (address === null) {
      throw new Error("The browser address is required");
    }
    await userEvent.click(address);
    await expect(canvasElement.ownerDocument.getSelection()?.toString()).toBe(
      page.url,
    );
    await userEvent.keyboard("{End}{Shift>}{ArrowLeft}{ArrowLeft}{/Shift}");
    const selected = canvasElement.ownerDocument.getSelection()?.toString();
    await expect(selected).toBe(page.url.slice(-2));
    await fireEvent.pointerDown(address);
    await fireEvent.click(address);
    await expect(canvasElement.ownerDocument.getSelection()?.toString()).toBe(
      selected,
    );
    address.blur();
    address.focus();
    await expect(canvasElement.ownerDocument.getSelection()?.toString()).toBe(
      page.url,
    );
    await expect(
      canvas.getByRole("textbox", { name: "Browser address" }),
    ).toHaveAttribute("inputmode", "url");
  },
} satisfies Story;

export const AddressExpandsOnFocus = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const address = canvas.getByRole("textbox", { name: "Browser address" });
    const width = address.getBoundingClientRect().width;
    await userEvent.click(address);
    await waitFor(() =>
      expect(address.getBoundingClientRect().width).toBeGreaterThan(width + 50),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Exit focused view" }),
    );
    await expect(
      canvas.queryByRole("dialog", { name: "Focus browser" }),
    ).toBeNull();
  },
} satisfies Story;

export const InvalidAddressKeepsFocus = {
  args: {
    addressValue: "https://user:password@example.test",
    addressError: true,
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("textbox", { name: "Browser address" }),
    );
    await userEvent.keyboard("{Enter}");
    await expect(args.onAddressSubmit).toHaveBeenCalledTimes(1);
    await expect(args.onAddressBlur).not.toHaveBeenCalled();
    await expect(
      canvas.getByRole("textbox", { name: "Browser address" }),
    ).toHaveFocus();
    await expect(canvas.getByRole("alert")).toBeVisible();
  },
} satisfies Story;

export const EmptyOffersNewTab = {
  args: { state: { type: "EMPTY" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await userEvent.click(canvas.getByRole("button", { name: "New tab" }));
    await expect(args.onCreatePage).toHaveBeenCalledTimes(1);
  },
} satisfies Story;

export const EmptyReadOnly = {
  args: { state: { type: "EMPTY" }, canCreate: false },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByRole("button", { name: "New tab" }),
    ).toBeDisabled();
    await expect(args.onCreatePage).not.toHaveBeenCalled();
  },
} satisfies Story;

export const MouseClickHasNoTouchEffect = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    await expect(actions).toHaveBeenCalledWith(
      frame,
      expect.objectContaining({ kind: "pointer", phase: "up" }),
    );
    await expect(
      canvasElement.ownerDocument.querySelector(
        "[data-browser-touch-feedback]",
      ),
    ).toBeNull();
  },
} satisfies Story;

export const PreciseTouchMarker = {
  render: (props) => <SessionBrowserPanel {...props} />,
  args: {
    touchView: {
      frame,
      direct: {
        active: false,
        pressed: false,
        sending: false,
        available: true,
        onToggle: fn(),
        onRelease: fn(),
      },
      cancel: fn(),
      viewWindowRef: { current: null },
      touch: {
        onPointerDown: fn(),
        onPointerMove: fn(),
        onPointerUp: fn(),
        onPointerCancel: fn(),
        onLostPointerCapture: fn(),
      },
      touchFeedback: { id: 1, x: 37, y: 43 },
      onTouchFeedbackEnd: fn(),
    },
  },
  play: async ({ canvasElement, args }) => {
    const body = canvasElement.ownerDocument.body;
    const marker = body.querySelector<HTMLElement>(
      "[data-browser-touch-feedback]",
    );
    if (marker === null) {
      throw new Error("The exact touch marker must be visible");
    }
    const view = body.ownerDocument.defaultView;
    if (view === null) {
      throw new Error("The touch marker requires a rendered window");
    }
    const animations = marker.getAnimations({ subtree: true });
    for (const animation of animations) {
      animation.pause();
      animation.currentTime = 50;
    }
    const position = marker.getBoundingClientRect();
    const dot = view.getComputedStyle(marker, "::after");
    const dotGeometry = [dot.width, dot.height, dot.transform];
    await expect(marker.style.left).toBe("37%");
    await expect(marker.style.top).toBe("43%");
    await expect(view.getComputedStyle(marker).pointerEvents).toBe("none");
    await expect(Number.parseFloat(dot.width)).toBeGreaterThan(0);
    for (const time of [200, 350]) {
      for (const animation of animations) {
        animation.currentTime = time;
      }
      const current = marker.getBoundingClientRect();
      const currentDot = view.getComputedStyle(marker, "::after");
      await expect([
        current.x,
        current.y,
        current.width,
        current.height,
      ]).toEqual([position.x, position.y, position.width, position.height]);
      await expect([
        currentDot.width,
        currentDot.height,
        currentDot.transform,
      ]).toEqual(dotGeometry);
    }
    await fireEvent.animationEnd(marker, { pseudoElement: "::before" });
    await expect(args.touchView?.onTouchFeedbackEnd).not.toHaveBeenCalled();
    await fireEvent.animationEnd(marker, { pseudoElement: "" });
    await expect(args.touchView?.onTouchFeedbackEnd).toHaveBeenCalledTimes(1);
  },
} satisfies Story;

export const AddressUsesUrlKeyboard = {
  play: async ({ canvasElement }) => {
    const address = within(canvasElement.ownerDocument.body).getByRole(
      "textbox",
      { name: "Browser address" },
    );
    await expect(address).toHaveAttribute("type", "url");
    await expect(address).toHaveAttribute("inputmode", "url");
    await expect(address).toHaveAttribute("autocapitalize", "off");
    await expect(address).toHaveAttribute("autocorrect", "off");
    await expect(address).toHaveAttribute("spellcheck", "false");
  },
} satisfies Story;

export const ReadOnly = {
  args: {
    state: { ...ready, canInput: false, canClose: false },
    navigationEnabled: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.queryByRole("textbox", { name: "Remote browser keyboard" }),
    ).toBeNull();
    await expect(
      canvas.getByRole("button", { name: "Close tab: Synthetic order" }),
    ).toBeDisabled();
    const surface = canvas.getByRole("region", { name: "Remote browser page" });
    await expect(surface).toHaveAttribute("tabindex", "-1");
    await fireEvent.keyDown(surface, { key: "Enter" });
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;

export const Disconnected = {
  tags: ["ci-contract"],
  args: { state: { ...ready, connection: "stale", canClose: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(canvas.getByText("Disconnected")).toBeVisible();
    await expect(canvas.getByRole("img")).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Close tab: Synthetic order" }),
    ).toBeDisabled();
    await expect(
      canvas.queryByRole("textbox", { name: "Remote browser keyboard" }),
    ).toBeNull();
    await userEvent.click(
      canvas.getByRole("button", { name: "Browser actions" }),
    );
    await expect(
      await canvas.findByRole("menuitem", {
        name: "Refresh browser connection",
      }),
    ).toBeEnabled();
  },
} satisfies Story;

export const Dialog = {
  args: {
    state: {
      ...ready,
      dialog: promptDialog,
      status: { ...initialDialogStatus, navigation_id: frame.navigation_id },
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByRole("textbox", { name: "Dialog response" }),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Dismiss" }));
    await expect(args.onDialogResponse).toHaveBeenCalledWith(false);
  },
} satisfies Story;
export const ReadOnlyDialog = {
  args: {
    state: {
      ...ready,
      canInput: false,
      canClose: false,
      dialog: { id: "dialog", type: "confirm", message: "Continue?" },
      status: {
        ...initialDialogStatus,
        allow_input: false,
        dialog: { id: "dialog", type: "confirm", message: "Continue?" },
      },
    },
  },
} satisfies Story;
export const InitialDialogBeforeImage = {
  args: {
    state: {
      ...ready,
      image: null,
      status: initialDialogStatus,
      dialog: promptDialog,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(canvas.queryByRole("img")).toBeNull();
    await expect(canvas.getByRole("button", { name: "Accept" })).toBeEnabled();
    await expect(
      canvas.queryByRole("textbox", { name: "Remote browser keyboard" }),
    ).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Accept" }));
    await expect(dialogMessages).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: "input",
        attachment_id: frame.attachment_id,
        sequence: 1,
        source: null,
        action: {
          kind: "dialog",
          dialog_id: promptDialog.id,
          accept: true,
          text: null,
        },
      }),
    );
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;
export const NavigationDialogAfterStaleImage = {
  args: {
    state: { ...ready, status: initialDialogStatus, dialog: promptDialog },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByRole("region", { name: "Remote browser page" }),
    ).toHaveAttribute("tabindex", "-1");
    await userEvent.click(canvas.getByRole("button", { name: "Dismiss" }));
    await expect(dialogMessages).toHaveBeenLastCalledWith(
      expect.objectContaining({ source: null }),
    );
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;
export const ReadOnlyDialogBeforeImage = {
  args: {
    state: {
      ...ready,
      image: null,
      status: { ...initialDialogStatus, allow_input: false },
      dialog: promptDialog,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(canvas.getByRole("button", { name: "Accept" })).toBeDisabled();
    await expect(
      canvas.getByRole("button", { name: "Dismiss" }),
    ).toBeDisabled();
    await expect(dialogMessages).not.toHaveBeenCalled();
  },
} satisfies Story;
export const StaleCoordinates = {
  tags: ["ci-contract"],
  args: {
    state: { ...ready, status: { ...initialDialogStatus, dialog: null } },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const surface = canvas.getByRole("region", { name: "Remote browser page" });
    const updating = canvas.getByRole("status", { name: "Updating page…" });
    await expect(updating).toBeVisible();
    await expect(updating).toHaveTextContent("");
    await expect(canvas.getByRole("img")).toBeVisible();
    await expect(
      canvas.getByRole("textbox", { name: "Remote browser keyboard" }),
    ).toHaveAttribute("readonly");
    await expect(surface).toHaveAttribute("tabindex", "-1");
    await fireEvent.keyDown(surface, { key: "Enter" });
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;
export const Conflict = {
  tags: ["ci-contract"],
  args: { state: { ...ready, conflict: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByText(
        "Another interaction is in progress. Try again when it finishes.",
      ),
    ).toBeVisible();
  },
} satisfies Story;
export const UnknownOutcome = {
  tags: ["ci-contract"],
  args: { state: { ...ready, outcomeUnknown: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByText(
        "Input result unconfirmed. Check the page before retrying.",
      ),
    ).toBeVisible();
  },
} satisfies Story;
export const CloseFailed = { args: { closeError: true } } satisfies Story;
export const Loading = { args: { state: { type: "LOADING" } } } satisfies Story;
export const Empty = { args: { state: { type: "EMPTY" } } } satisfies Story;
export const Unavailable = {
  args: {
    state: {
      type: "UNAVAILABLE",
      reason: "The current Runtime does not have an available browser.",
    },
  },
} satisfies Story;
export const Connecting = {
  args: { state: { ...ready, connection: "connecting", image: null } },
} satisfies Story;
export const LiveTransportUnavailable = {
  tags: ["ci-contract"],
  args: {
    state: {
      ...ready,
      connection: "unavailable",
      image: null,
      canInput: false,
      canClose: true,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByRole("button", { name: "Close tab: Synthetic order" }),
    ).toBeEnabled();
    await expect(
      canvas.getByRole("textbox", { name: "Remote browser keyboard" }),
    ).toHaveAttribute("readonly");
    await expect(
      canvas.getByText(
        "Browser connection unavailable. Reconnect from the Browser menu.",
      ),
    ).toBeVisible();
  },
} satisfies Story;
export const Mobile = {
  decorators: [
    (Story) => (
      <Box maw={rem(390)}>
        <Story />
      </Box>
    ),
  ],
} satisfies Story;
export const NarrowDesktop = {
  decorators: [
    (Story) => (
      <Box maw={rem(520)}>
        <Story />
      </Box>
    ),
  ],
} satisfies Story;
export const LongLabels = {
  args: {
    state: {
      ...ready,
      pages: [
        {
          ...page,
          taskLabel:
            "Review a delivery with a very long task label and an equally long page title",
          title:
            "Current synthetic order · Long page title for overflow validation",
        },
      ],
    },
  },
} satisfies Story;
export const KeyboardAndComposition = {
  tags: ["ci-contract"],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    await expect(keyboard).toHaveFocus();
    actions.mockClear();
    await userEvent.keyboard("x");
    await expect(actions).toHaveBeenCalledWith(frame, {
      kind: "composition",
      phase: "commit",
      text: "x",
    });
    actions.mockClear();
    await fireEvent.compositionStart(keyboard);
    await fireEvent.input(keyboard, {
      target: { value: "x한" },
      isComposing: true,
    });
    await fireEvent.compositionEnd(keyboard, { data: "한" });
    await fireEvent.input(keyboard, { target: { value: "x한" }, data: "한" });
    await expect(actions).toHaveBeenCalledTimes(2);
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "composition",
      phase: "commit",
      text: "한",
    });
    await userEvent.keyboard("{Tab}");
    await expect(keyboard).not.toHaveFocus();
  },
} satisfies Story;
export const KoreanWithoutCompositionEvents = {
  tags: ["ci-contract"],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    actions.mockClear();
    await fireEvent.input(keyboard, {
      target: { value: "ㅇ" },
      data: "ㅇ",
      inputType: "insertText",
    });
    await expect(keyboard).toHaveValue("ㅇ");
    // iOS Korean replaces an ordinary insertion, without isComposing.
    await fireEvent(
      keyboard,
      new InputEvent("beforeinput", {
        bubbles: true,
        cancelable: true,
        inputType: "deleteContentBackward",
      }),
    );
    await expect(keyboard).toHaveValue("ㅇ");
    await fireEvent.input(keyboard, {
      target: { value: "" },
      inputType: "deleteContentBackward",
    });
    await fireEvent.input(keyboard, {
      target: { value: "아" },
      data: "아",
      inputType: "insertText",
    });
    await expect(keyboard).toHaveValue("아");
    await expect(actions.mock.calls.map(([, action]) => action)).toEqual([
      { kind: "composition", phase: "start", text: null },
      { kind: "composition", phase: "commit", text: "ㅇ" },
      { kind: "text_edit", delete_before: 1, text: "" },
      { kind: "composition", phase: "start", text: null },
      { kind: "composition", phase: "commit", text: "아" },
    ]);
    actions.mockClear();
    if (keyboard instanceof HTMLTextAreaElement) {
      keyboard.setSelectionRange(keyboard.value.length, keyboard.value.length);
    }
    await userEvent.keyboard("{Backspace}");
    await expect(keyboard).toHaveValue("");
    await expect(actions).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{Tab}");
    await expect(keyboard).not.toHaveFocus();
  },
} satisfies Story;
export const CancelledCompositionDoesNotCommit = {
  tags: ["ci-contract"],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    await expect(keyboard).toHaveFocus();
    actions.mockClear();
    await fireEvent.compositionStart(keyboard);
    await userEvent.tab();
    await expect(keyboard).not.toHaveFocus();
    await fireEvent.compositionEnd(keyboard, { data: "cancelled" });
    await fireEvent.input(keyboard, {
      target: { value: "cancelled" },
      data: "cancelled",
    });
    await expect(actions).toHaveBeenCalledTimes(2);
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "composition",
      phase: "cancel",
      text: null,
    });
  },
} satisfies Story;
export const HeldKeyCleanupOnBlur = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    await expect(keyboard).toHaveFocus();
    actions.mockClear();
    await fireEvent.keyDown(keyboard, { key: "Shift", shiftKey: true });
    await fireEvent.keyDown(keyboard, { key: "ArrowLeft", shiftKey: true });
    await userEvent.tab();
    await expect(actions).toHaveBeenCalledWith(frame, {
      kind: "key",
      phase: "up",
      key: "Shift",
    });
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "key",
      phase: "up",
      key: "ArrowLeft",
    });
  },
} satisfies Story;
export const AccessChanged = {
  args: { state: { type: "ACCESS_CHANGED" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(canvas.queryByRole("img")).toBeNull();
    await expect(canvas.queryByRole("combobox")).toBeNull();
    await expect(canvas.getByText("Browser access changed")).toBeVisible();
  },
} satisfies Story;
export const DecodedImageDimensionsMustMatch = {
  args: {
    state: {
      ...ready,
      image:
        ready.image === null
          ? null
          : { ...ready.image, frame: { ...frame, width: 1281 } },
    },
  },
  play: async ({ args }) => {
    await waitFor(() => expect(args.onFrameError).toHaveBeenCalled());
    await expect(args.onFrameDisplayed).not.toHaveBeenCalled();
  },
} satisfies Story;
export const ExplicitRemoteTabKeys = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await waitFor(() =>
      expect(
        canvas.getByRole("button", { name: "Exit focused view" }),
      ).toHaveFocus(),
    );
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("button", { name: "Browser actions" }),
    );
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Send Tab" }),
    );
    await waitFor(() =>
      expect(
        canvasElement.ownerDocument.querySelector("[data-menu-dropdown]"),
      ).toBeNull(),
    );
    await expect(actions).toHaveBeenCalledTimes(2);
    await expect(actions).toHaveBeenNthCalledWith(1, frame, {
      kind: "key",
      phase: "down",
      key: "Tab",
    });
    await expect(actions).toHaveBeenNthCalledWith(2, frame, {
      kind: "key",
      phase: "up",
      key: "Tab",
    });
    actions.mockClear();
    await userEvent.click(
      canvas.getByRole("button", { name: "Browser actions" }),
    );
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Send Shift+Tab" }),
    );
    await waitFor(() =>
      expect(
        canvasElement.ownerDocument.querySelector("[data-menu-dropdown]"),
      ).toBeNull(),
    );
    await expect(actions).toHaveBeenCalledTimes(4);
    await expect(actions).toHaveBeenNthCalledWith(1, frame, {
      kind: "key",
      phase: "down",
      key: "Shift",
    });
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "key",
      phase: "up",
      key: "Shift",
    });
  },
} satisfies Story;
export const NativeMobileEditingIntent = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    await expect(keyboard).toHaveFocus();
    actions.mockClear();
    await fireEvent(
      keyboard,
      new InputEvent("beforeinput", {
        inputType: "deleteContentBackward",
        bubbles: true,
        cancelable: true,
      }),
    );
    await expect(actions).toHaveBeenCalledTimes(2);
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "key",
      phase: "up",
      key: "Backspace",
    });
    actions.mockClear();
    await fireEvent(
      keyboard,
      new InputEvent("beforeinput", {
        inputType: "insertLineBreak",
        bubbles: true,
        cancelable: true,
      }),
    );
    await expect(actions).toHaveBeenCalledTimes(2);
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "key",
      phase: "up",
      key: "Enter",
    });
  },
} satisfies Story;
export const UppercaseTextareaText = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const surface = canvas.getByRole("region", { name: "Remote browser page" });
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await clickBrowserViewport(surface);
    await expect(keyboard).toHaveFocus();
    await expect(actions).toHaveBeenCalledTimes(2);
    await expect(actions).toHaveBeenNthCalledWith(
      1,
      frame,
      expect.objectContaining({ kind: "pointer", phase: "down" }),
    );
    await expect(actions).toHaveBeenLastCalledWith(
      frame,
      expect.objectContaining({ kind: "pointer", phase: "up" }),
    );
    actions.mockClear();
    await userEvent.keyboard(
      "{Shift>}S{/Shift}ynthetic {Shift>}GUI{/Shift} input",
    );
    const commits = actions.mock.calls.flatMap(([, action]) =>
      action.kind === "composition" &&
      action.phase === "commit" &&
      action.text !== null
        ? [action.text]
        : [],
    );
    await expect(commits.join("")).toBe("Synthetic GUI input");
    await expect(
      actions.mock.calls.every(([, action]) => action.kind !== "key"),
    ).toBe(true);
  },
} satisfies Story;
export const TextareaShortcutModifiers = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    actions.mockClear();
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    await expect(actions).toHaveBeenCalledTimes(4);
    await expect(actions).toHaveBeenNthCalledWith(1, frame, {
      kind: "key",
      phase: "down",
      key: "Shift",
    });
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "key",
      phase: "up",
      key: "Shift",
    });
    for (const modifier of ["Control", "Meta", "Alt"]) {
      actions.mockClear();
      await userEvent.keyboard(`{${modifier}>}a{/${modifier}}`);
      await expect(actions).toHaveBeenCalledTimes(4);
      await expect(actions).toHaveBeenNthCalledWith(1, frame, {
        kind: "key",
        phase: "down",
        key: modifier,
      });
      await expect(actions).toHaveBeenLastCalledWith(frame, {
        kind: "key",
        phase: "up",
        key: modifier,
      });
    }
    actions.mockClear();
    await userEvent.keyboard("{Shift>}{ArrowLeft}S{/Shift}");
    const values = actions.mock.calls.map(([, action]) => action);
    const released = values.findIndex(
      (action) =>
        action.kind === "key" &&
        action.key === "Shift" &&
        action.phase === "up",
    );
    const insertion = values.findIndex(
      (action) => action.kind === "composition" && action.phase === "start",
    );
    await expect(released).toBeGreaterThanOrEqual(0);
    await expect(insertion).toBeGreaterThan(released);
  },
} satisfies Story;

export const OutsideClickCancelsComposition = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await clickBrowserViewport(
      canvas.getByRole("region", { name: "Remote browser page" }),
    );
    await expect(keyboard).toHaveFocus();
    actions.mockClear();
    await fireEvent.compositionStart(keyboard);
    await userEvent.click(
      canvas.getByRole("button", { name: "Browser actions" }),
    );
    await expect(keyboard).not.toHaveFocus();
    await fireEvent.compositionEnd(keyboard, { data: "cancelled" });
    await fireEvent.input(keyboard, {
      target: { value: "cancelled" },
      data: "cancelled",
    });
    await expect(actions).toHaveBeenCalledTimes(2);
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "composition",
      phase: "cancel",
      text: null,
    });
  },
} satisfies Story;

export const MultiplePages = {
  args: {
    state: {
      ...ready,
      pages: [
        page,
        {
          ...page,
          target: { ...target, page_id: "second-synthetic-page" },
          title: "Delivery receipt",
        },
      ],
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByRole("tab", { name: "Synthetic order" }),
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.click(
      canvas.getByRole("tab", { name: "Delivery receipt" }),
    );
    await expect(args.onSelect).toHaveBeenCalledWith({
      ...target,
      page_id: "second-synthetic-page",
    });
  },
} satisfies Story;

export const NativeNavigationControls = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const address = canvas.getByRole("textbox", { name: "Browser address" });
    await expect(address).not.toHaveAttribute("readonly");
    await userEvent.click(address);
    await fireEvent.change(address, {
      target: { value: "https://example.test/next" },
    });
    await expect(args.onAddressChange).toHaveBeenCalledWith(
      "https://example.test/next",
    );
    await fireEvent.keyDown(address, { key: "Enter" });
    await expect(args.onAddressSubmit).toHaveBeenCalledTimes(1);
    for (const [name, action] of [
      ["Go back", "back"],
      ["Go forward", "forward"],
      ["Reload page", "reload"],
    ]) {
      await userEvent.click(canvas.getByRole("button", { name }));
      await expect(args.onNavigate).toHaveBeenLastCalledWith({
        kind: "navigation",
        action,
        url: null,
      });
    }
    await expect(args.onRetry).not.toHaveBeenCalled();
  },
} satisfies Story;

export const ReadOnlyNavigation = {
  args: {
    state: { ...ready, canInput: false, canClose: false },
    navigationEnabled: false,
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(
      canvas.getByRole("textbox", { name: "Browser address" }),
    ).toHaveAttribute("readonly");
    for (const name of ["Go back", "Go forward", "Reload page"]) {
      await expect(canvas.getByRole("button", { name })).toBeDisabled();
    }
    await expect(args.onNavigate).not.toHaveBeenCalled();
  },
} satisfies Story;

export const KeyboardEntryAndEscape = {
  render: (props): ReactElement => (
    <>
      <BrowserFixture {...props} />
      <Button>Outside browser panel</Button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const keyboard = canvas.getByRole("textbox", {
      name: "Remote browser keyboard",
    });
    await waitFor(() =>
      expect(
        canvas.getByRole("button", { name: "Exit focused view" }),
      ).toHaveFocus(),
    );
    const menu = canvas.getByRole("button", { name: "Browser actions" });
    menu.focus();
    actions.mockClear();
    await userEvent.tab();
    await expect(keyboard).toHaveFocus();
    await userEvent.keyboard("{Shift>}S{/Shift}");
    await expect(actions).toHaveBeenLastCalledWith(frame, {
      kind: "composition",
      phase: "commit",
      text: "S",
    });
    await userEvent.tab();
    await expect(
      canvas.getByRole("button", { name: "Exit focused view" }),
    ).toHaveFocus();
    await userEvent.tab({ shift: true });
    await expect(keyboard).toHaveFocus();
    await userEvent.tab({ shift: true });
    await expect(menu).toHaveFocus();
  },
} satisfies Story;
