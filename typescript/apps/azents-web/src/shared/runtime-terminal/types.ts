import type { RuntimeTerminalProjectionResponse } from "@azents/public-client";

export type RuntimeTerminalPresentation = "collapsed" | "docked" | "focused";

export type RuntimeTerminalConnectionState =
  | { type: "idle" }
  | { type: "connecting" }
  | { type: "connected"; shellLabel: string }
  | { type: "reconnecting" }
  | { type: "terminating" }
  | { type: "exited" }
  | { type: "revoked" }
  | { type: "error" };

export interface RuntimeTerminalViewState {
  projection: RuntimeTerminalProjectionResponse | null;
  projectionLoading: boolean;
  presentation: RuntimeTerminalPresentation;
  connection: RuntimeTerminalConnectionState;
  replayTruncated: boolean;
  hasNewOutput: boolean;
  ctrlActive: boolean;
  altActive: boolean;
}

export interface RuntimeTerminalContainerOutput extends RuntimeTerminalViewState {
  hostRef: (node: HTMLDivElement | null) => void;
  onExpand: () => void;
  onFocus: () => void;
  onCollapse: () => void;
  onReturnToDock: () => void;
  onTerminate: () => void;
  onRetry: () => void;
  onToggleCtrl: () => void;
  onToggleAlt: () => void;
  onSoftwareKey: (key: string) => void;
  onFocusKeyboard: () => void;
  dockHeight: number;
  onDockResizeStart: (clientY: number) => void;
  onDockResizeBy: (delta: number) => void;
}
