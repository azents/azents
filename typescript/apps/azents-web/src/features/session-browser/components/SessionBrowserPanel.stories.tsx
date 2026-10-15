import { Box, Button, rem } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import {
  expect,
  fireEvent,
  fn,
  userEvent,
  waitFor,
  within,
} from "storybook/test";
import { BrowserConnection, emptyBrowserLiveState } from "../connection";
import { useBrowserInteraction } from "../containers/useBrowserInteraction";
import { useBrowserTouchView } from "../containers/useBrowserTouchView";
import { browserDialogInput, browserFrameMatchesStatus } from "../input";
import { SessionBrowserPanel } from "./SessionBrowserPanel";
import type {
  BrowserFrame,
  BrowserInput,
  BrowserInputAction,
  BrowserPageChoice,
  BrowserStatus,
  BrowserViewState,
} from "../types";
import type { SessionBrowserPanelProps } from "./SessionBrowserPanel";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

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
  props: SessionBrowserPanelProps & { reportActions?: boolean },
): ReactElement {
  const [focused, setFocused] = useState(props.focused);
  const [zoom, setZoom] = useState(props.zoom);
  const [counts, setCounts] = useState({
    down: 0,
    up: 0,
    cancel: 0,
    wheel: 0,
    text: 0,
  });
  const onAction = (
    source: BrowserFrame,
    action: BrowserInputAction,
  ): boolean => {
    if (props.reportActions) {
      if (action.kind === "pointer" && action.phase !== "move") {
        const phase = action.phase;
        setCounts((value) => ({ ...value, [phase]: value[phase] + 1 }));
      } else if (action.kind === "wheel") {
        setCounts((value) => ({ ...value, wheel: value.wheel + 1 }));
      } else if (action.kind === "composition" && action.phase === "commit") {
        setCounts((value) => ({ ...value, text: value.text + 1 }));
      }
    }
    return actions(source, action);
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
    enabled: active && focused,
    frame:
      props.state.type === "READY" ? (props.state.image?.frame ?? null) : null,
    onAction,
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
    frame:
      props.state.type === "READY" ? (props.state.image?.frame ?? null) : null,
    zoom,
    onZoomChange: setZoom,
    onAction,
    keyboardRef: interaction.keyboardRef,
    cancelInput: interaction.cancel,
  });
  return (
    <Box h={rem(800)} w="100%" maw={rem(640)}>
      <SessionBrowserPanel
        {...props}
        interaction={interaction.interaction}
        keyboardRef={interaction.keyboardRef}
        touchView={touchView}
        focused={focused}
        zoom={zoom}
        onToggleFocus={() => {
          interaction.cancel();
          setFocused((value) => !value);
          props.onToggleFocus();
        }}
        onZoomChange={(value) => {
          interaction.cancel();
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

const meta = {
  component: SessionBrowserPanel,
  parameters: { layout: "fullscreen" },
  render: (props) => <BrowserFixture {...props} />,
  args: {
    focused: true,
    focusViewport: null,
    zoom: 1,
    onToggleFocus: fn(),
    onZoomChange: fn(),
    state: ready,
    addressValue: page.url,
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
    interaction: null,
    touchView: null,
  },
  beforeEach: (): void => {
    actions.mockClear();
    dialogMessages.mockClear();
  },
} satisfies Meta<typeof SessionBrowserPanel>;
export default meta;
type Story = StoryObj<typeof meta>;

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
        url: `data:image/svg+xml,${encodeURIComponent(svg.replaceAll('width="800"', 'width="1280"').replaceAll('height="900"', 'height="800"'))}`,
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
  args: { state: { ...ready, connection: "stale", canClose: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    await expect(canvas.getByText(/last received image/)).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Close tab: Synthetic order" }),
    ).toBeDisabled();
    await expect(
      canvas.queryByRole("textbox", { name: "Remote browser keyboard" }),
    ).toBeNull();
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
  args: {
    state: { ...ready, status: { ...initialDialogStatus, dialog: null } },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const surface = canvas.getByRole("region", { name: "Remote browser page" });
    await expect(surface).toHaveAttribute("tabindex", "-1");
    await fireEvent.keyDown(surface, { key: "Enter" });
    await expect(actions).not.toHaveBeenCalled();
  },
} satisfies Story;
export const Conflict = {
  args: { state: { ...ready, conflict: true } },
} satisfies Story;
export const UnknownOutcome = {
  args: { state: { ...ready, outcomeUnknown: true } },
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
      canvas.queryByRole("textbox", { name: "Remote browser keyboard" }),
    ).toBeNull();
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
      target: { value: "한" },
      isComposing: true,
    });
    await fireEvent.compositionEnd(keyboard, { data: "한" });
    await fireEvent.input(keyboard, { target: { value: "한" }, data: "한" });
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
export const CancelledCompositionDoesNotCommit = {
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
