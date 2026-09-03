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
