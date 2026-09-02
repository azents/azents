"use client";

import { useLocalStorage } from "@mantine/hooks";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  classifyTerminalOutputSequence,
  isTerminalProjectionConnectable,
  isTerminalProjectionReconnectable,
  reconcilePendingTerminalInput,
  resolveReplayAcknowledgement,
  shouldRestoreChatForTerminalProjection,
} from "../protocol";
import {
  applyTerminalKeyModifiers,
  decodeTerminalOutputFrame,
  decodeTerminalServerControl,
  encodeTerminalInputFrame,
  splitTerminalInput,
} from "../wire";
import type {
  RuntimeTerminalConnectionState,
  RuntimeTerminalPresentation,
  RuntimeTerminalViewState,
} from "../types";

const SUBPROTOCOL = "azents.terminal.v1";
const HEARTBEAT_MS = 15_000;
const RECONNECT_MS = 1_000;
const CONTROL_COALESCE_MS = 125;
const MAX_PENDING_INPUT_BYTES = 64 * 1024;
const MIN_DOCK_HEIGHT = 180;
const MAX_DOCK_HEIGHT = 560;

type ProtocolPhase =
  | "closed"
  | "awaiting_accepted"
  | "awaiting_replay_begin"
  | "replaying"
  | "live";

interface RuntimeTerminalContainerProps {
  handle: string;
  agentId: string;
  sessionId: string;
  mobile: boolean;
}

interface AcceptedReplay {
  minimumSequence: number;
  maximumSequence: number;
  truncated: boolean;
  truncationSeen: boolean;
}

interface ActiveReplay {
  maximumSequence: number;
  ended: boolean;
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

function sendSocketControl(socket: WebSocket, control: object): void {
  if (socket.readyState !== WebSocket.OPEN) {
    throw new Error("Terminal WebSocket is not open.");
  }
  socket.send(JSON.stringify(control));
}

function closeSocket(socket: WebSocket): void {
  if (
    socket.readyState === WebSocket.OPEN ||
    socket.readyState === WebSocket.CONNECTING
  ) {
    socket.close();
  }
}

export function useRuntimeTerminalContainer({
  handle,
  agentId,
  sessionId,
  mobile,
}: RuntimeTerminalContainerProps): RuntimeTerminalContainerOutput {
  const resource = useMemo(
    () => ({ handle, agentId, sessionId }),
    [agentId, handle, sessionId],
  );
  const resourceKey = `${handle}\u0000${agentId}\u0000${sessionId}`;
  const projectionQuery = trpc.terminal.projection.useQuery(resource, {
    refetchInterval: 5_000,
    retry: false,
  });
  const ticketMutation = trpc.terminal.ticket.useMutation();
  const [presentation, setPresentation] =
    useState<RuntimeTerminalPresentation>("collapsed");
  const presentationRef = useRef<RuntimeTerminalPresentation>("collapsed");
  const [connection, setConnection] = useState<RuntimeTerminalConnectionState>({
    type: "idle",
  });
  const [replayTruncated, setReplayTruncated] = useState(false);
  const [hasNewOutput, setHasNewOutput] = useState(false);
  const [ctrlActive, setCtrlActive] = useState(false);
  const [altActive, setAltActive] = useState(false);
  const [dockHeight, setDockHeight] = useLocalStorage<number>({
    key: "runtime-terminal-dock-height",
    defaultValue: 260,
  });

  const projectionRef = useRef(projectionQuery.data);
  projectionRef.current = projectionQuery.data;
  const resourceKeyRef = useRef(resourceKey);
  const terminalRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const hostNodeRef = useRef<HTMLDivElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const intentionalSocketsRef = useRef(new WeakSet<WebSocket>());
  const reconnectTimerRef = useRef<number | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const outputAckTimerRef = useRef<number | null>(null);
  const pendingOutputAckRef = useRef<number | null>(null);
  const pendingResizeRef = useRef<{ columns: number; rows: number } | null>(
    null,
  );
  const resizeSequenceRef = useRef(0);
  const heartbeatSequenceRef = useRef(0);
  const terminalIdRef = useRef<string | null>(null);
  const nextInputSequenceRef = useRef(1);
  const acceptedNextInputSequenceRef = useRef(1);
  const pendingInputRef = useRef(new Map<number, Uint8Array>());
  const pendingInputBytesRef = useRef(0);
  const highestOutputScheduledRef = useRef(0);
  const highestOutputRenderedRef = useRef(0);
  const acceptedReplayRef = useRef<AcceptedReplay | null>(null);
  const activeReplayRef = useRef<ActiveReplay | null>(null);
  const protocolPhaseRef = useRef<ProtocolPhase>("closed");
  const pendingShellLabelRef = useRef("Terminal");
  const inputEnabledRef = useRef(false);
  const activatedRef = useRef(false);
  const terminateRequestedRef = useRef(false);
  const connectAttemptRef = useRef(0);
  const connectInFlightRef = useRef(false);
  const socketGenerationRef = useRef(0);
  const connectRef = useRef<() => void>(() => {});
  const sendInputTextRef = useRef<(text: string) => void>(() => {});
  const dockResizeCleanupRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(true);

  const clearReconnectTimer = useCallback((): void => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const clearHeartbeatTimer = useCallback((): void => {
    if (heartbeatTimerRef.current !== null) {
      window.clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  const clearResizeTimer = useCallback((): void => {
    if (resizeTimerRef.current !== null) {
      window.clearTimeout(resizeTimerRef.current);
      resizeTimerRef.current = null;
    }
  }, []);

  const clearOutputAckTimer = useCallback((): void => {
    if (outputAckTimerRef.current !== null) {
      window.clearTimeout(outputAckTimerRef.current);
      outputAckTimerRef.current = null;
    }
    pendingOutputAckRef.current = null;
  }, []);

  const removePendingInputThrough = useCallback((sequence: number): void => {
    for (const [pendingSequence, data] of pendingInputRef.current) {
      if (pendingSequence <= sequence) {
        pendingInputRef.current.delete(pendingSequence);
        pendingInputBytesRef.current -= data.byteLength;
      }
    }
  }, []);

  const queueResize = useCallback((columns: number, rows: number): void => {
    pendingResizeRef.current = { columns, rows };
    if (resizeTimerRef.current !== null) {
      return;
    }
    resizeTimerRef.current = window.setTimeout(() => {
      resizeTimerRef.current = null;
      const pending = pendingResizeRef.current;
      pendingResizeRef.current = null;
      const socket = socketRef.current;
      if (
        pending === null ||
        socket?.readyState !== WebSocket.OPEN ||
        protocolPhaseRef.current !== "live"
      ) {
        return;
      }
      resizeSequenceRef.current += 1;
      try {
        sendSocketControl(socket, {
          type: "resize",
          sequence: resizeSequenceRef.current,
          columns: pending.columns,
          rows: pending.rows,
        });
      } catch {
        closeSocket(socket);
      }
    }, CONTROL_COALESCE_MS);
  }, []);

  const queueOutputAcknowledgement = useCallback((sequence: number): void => {
    pendingOutputAckRef.current = Math.max(
      pendingOutputAckRef.current ?? 0,
      sequence,
    );
    if (outputAckTimerRef.current !== null) {
      return;
    }
    outputAckTimerRef.current = window.setTimeout(() => {
      outputAckTimerRef.current = null;
      const pending = pendingOutputAckRef.current;
      pendingOutputAckRef.current = null;
      const socket = socketRef.current;
      if (
        pending === null ||
        socket?.readyState !== WebSocket.OPEN ||
        protocolPhaseRef.current !== "live"
      ) {
        return;
      }
      try {
        sendSocketControl(socket, {
          type: "output_ack",
          sequence: pending,
        });
      } catch {
        closeSocket(socket);
      }
    }, CONTROL_COALESCE_MS);
  }, []);

  const fitAndResize = useCallback((): void => {
    const fit = fitRef.current;
    const terminal = terminalRef.current;
    if (fit === null || terminal === null || hostNodeRef.current === null) {
      return;
    }
    fit.fit();
    if (terminal.cols < 1 || terminal.rows < 1) {
      return;
    }
    queueResize(terminal.cols, terminal.rows);
  }, [queueResize]);

  const failSocket = useCallback((socket: WebSocket): void => {
    intentionalSocketsRef.current.add(socket);
    inputEnabledRef.current = false;
    protocolPhaseRef.current = "closed";
    setConnection({ type: "error" });
    closeSocket(socket);
  }, []);

  const sendPendingInput = useCallback(
    (socket: WebSocket): void => {
      removePendingInputThrough(acceptedNextInputSequenceRef.current - 1);
      const reconciled = reconcilePendingTerminalInput(
        pendingInputRef.current,
        acceptedNextInputSequenceRef.current,
      );
      nextInputSequenceRef.current = reconciled.nextSequence;
      for (const item of reconciled.resend) {
        socket.send(encodeTerminalInputFrame(item.sequence, item.data));
      }
    },
    [removePendingInputThrough],
  );

  const requestTerminate = useCallback((socket: WebSocket): void => {
    if (
      socket.readyState !== WebSocket.OPEN ||
      protocolPhaseRef.current !== "live"
    ) {
      return;
    }
    intentionalSocketsRef.current.add(socket);
    inputEnabledRef.current = false;
    setConnection({ type: "terminating" });
    try {
      sendSocketControl(socket, { type: "terminate" });
    } catch {
      intentionalSocketsRef.current.delete(socket);
      setConnection({ type: "error" });
      closeSocket(socket);
    }
  }, []);

  const finishReplay = useCallback(
    (socket: WebSocket, generation: number): void => {
      const replay = activeReplayRef.current;
      if (replay === null) {
        failSocket(socket);
        return;
      }
      const acknowledgement = resolveReplayAcknowledgement({
        replayEnded: replay.ended,
        replayMaximumSequence: replay.maximumSequence,
        highestRenderedSequence: highestOutputRenderedRef.current,
      });
      if (acknowledgement === null) {
        return;
      }
      if (
        socketGenerationRef.current !== generation ||
        socketRef.current !== socket
      ) {
        return;
      }
      protocolPhaseRef.current = "live";
      activeReplayRef.current = null;
      clearOutputAckTimer();
      try {
        sendSocketControl(socket, {
          type: "output_ack",
          sequence: acknowledgement,
        });
        sendPendingInput(socket);
      } catch {
        failSocket(socket);
        return;
      }
      inputEnabledRef.current = true;
      setConnection({
        type: "connected",
        shellLabel: pendingShellLabelRef.current,
      });
      fitAndResize();
      if (terminateRequestedRef.current) {
        requestTerminate(socket);
      }
    },
    [
      clearOutputAckTimer,
      failSocket,
      fitAndResize,
      requestTerminate,
      sendPendingInput,
    ],
  );

  const scheduleReconnect = useCallback((): void => {
    if (
      !mountedRef.current ||
      !activatedRef.current ||
      !isTerminalProjectionReconnectable(projectionRef.current?.state ?? null)
    ) {
      return;
    }
    setConnection({ type: "reconnecting" });
    clearReconnectTimer();
    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null;
      connectRef.current();
    }, RECONNECT_MS);
  }, [clearReconnectTimer]);

  const connect = useCallback(async (): Promise<void> => {
    const projection = projectionRef.current;
    if (
      !mountedRef.current ||
      !activatedRef.current ||
      !isTerminalProjectionConnectable(projection?.state ?? null) ||
      connectInFlightRef.current ||
      socketRef.current?.readyState === WebSocket.OPEN ||
      socketRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }
    connectInFlightRef.current = true;
    const attempt = ++connectAttemptRef.current;
    clearReconnectTimer();
    setConnection((current) =>
      current.type === "reconnecting" ? current : { type: "connecting" },
    );
    try {
      const issued = await ticketMutation.mutateAsync(resource);
      if (attempt !== connectAttemptRef.current) {
        return;
      }
      if (issued.status !== "issued" || issued.ticket === null) {
        setConnection({ type: "error" });
        return;
      }
      const url = `${issued.websocketUrl}?ticket=${encodeURIComponent(issued.ticket)}`;
      const socket = new WebSocket(url, SUBPROTOCOL);
      const generation = ++socketGenerationRef.current;
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;
      protocolPhaseRef.current = "awaiting_accepted";
      inputEnabledRef.current = false;
      acceptedReplayRef.current = null;
      activeReplayRef.current = null;
      setReplayTruncated(false);

      socket.onopen = () => {
        if (
          socketGenerationRef.current !== generation ||
          socketRef.current !== socket
        ) {
          intentionalSocketsRef.current.add(socket);
          closeSocket(socket);
          return;
        }
        const terminal = terminalRef.current;
        fitRef.current?.fit();
        try {
          sendSocketControl(socket, {
            type: "attach",
            columns: Math.max(terminal?.cols ?? 80, 1),
            rows: Math.max(terminal?.rows ?? 24, 1),
            last_output_sequence: 0,
          });
        } catch {
          failSocket(socket);
        }
      };

      socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
        if (
          socketGenerationRef.current !== generation ||
          socketRef.current !== socket
        ) {
          return;
        }
        if (event.data instanceof ArrayBuffer) {
          if (
            protocolPhaseRef.current !== "replaying" &&
            protocolPhaseRef.current !== "live"
          ) {
            failSocket(socket);
            return;
          }
          let output: ReturnType<typeof decodeTerminalOutputFrame>;
          try {
            output = decodeTerminalOutputFrame(event.data);
            const classification = classifyTerminalOutputSequence(
              highestOutputScheduledRef.current,
              output.sequence,
            );
            if (classification === "duplicate") {
              if (
                protocolPhaseRef.current === "live" &&
                output.sequence <= highestOutputRenderedRef.current
              ) {
                queueOutputAcknowledgement(highestOutputRenderedRef.current);
              }
              return;
            }
          } catch {
            failSocket(socket);
            return;
          }
          const terminal = terminalRef.current;
          if (terminal === null) {
            failSocket(socket);
            return;
          }
          highestOutputScheduledRef.current = output.sequence;
          terminal.write(output.bytes, () => {
            if (
              socketGenerationRef.current !== generation ||
              socketRef.current !== socket
            ) {
              return;
            }
            highestOutputRenderedRef.current = Math.max(
              highestOutputRenderedRef.current,
              output.sequence,
            );
            if (protocolPhaseRef.current === "live") {
              queueOutputAcknowledgement(highestOutputRenderedRef.current);
            } else {
              finishReplay(socket, generation);
            }
          });
          if (presentationRef.current === "collapsed") {
            setHasNewOutput(true);
          }
          return;
        }

        let control: ReturnType<typeof decodeTerminalServerControl>;
        try {
          control = decodeTerminalServerControl(event.data);
        } catch {
          failSocket(socket);
          return;
        }
        switch (control.type) {
          case "accepted": {
            if (protocolPhaseRef.current !== "awaiting_accepted") {
              failSocket(socket);
              return;
            }
            if (terminalIdRef.current !== control.terminalId) {
              terminalIdRef.current = control.terminalId;
              pendingInputRef.current.clear();
              pendingInputBytesRef.current = 0;
              nextInputSequenceRef.current = 1;
              highestOutputScheduledRef.current = 0;
              highestOutputRenderedRef.current = 0;
            }
            acceptedNextInputSequenceRef.current = control.nextInputSequence;
            pendingShellLabelRef.current = control.shellLabel;
            acceptedReplayRef.current = {
              minimumSequence: control.replayMinimumSequence,
              maximumSequence: control.replayMaximumSequence,
              truncated: control.replayTruncated,
              truncationSeen: false,
            };
            protocolPhaseRef.current = "awaiting_replay_begin";
            clearHeartbeatTimer();
            heartbeatTimerRef.current = window.setInterval(() => {
              if (
                socketRef.current !== socket ||
                socket.readyState !== WebSocket.OPEN
              ) {
                return;
              }
              heartbeatSequenceRef.current += 1;
              try {
                sendSocketControl(socket, {
                  type: "heartbeat",
                  sequence: heartbeatSequenceRef.current,
                });
              } catch {
                closeSocket(socket);
              }
            }, HEARTBEAT_MS);
            return;
          }
          case "replay_begin": {
            const acceptedReplay = acceptedReplayRef.current;
            if (
              protocolPhaseRef.current !== "awaiting_replay_begin" ||
              acceptedReplay === null ||
              control.minimumSequence !== acceptedReplay.minimumSequence ||
              control.maximumSequence !== acceptedReplay.maximumSequence ||
              control.minimumSequence > control.maximumSequence + 1 ||
              control.maximumSequence < control.minimumSequence - 1
            ) {
              failSocket(socket);
              return;
            }
            terminalRef.current?.reset();
            highestOutputRenderedRef.current = control.minimumSequence - 1;
            highestOutputScheduledRef.current = control.minimumSequence - 1;
            activeReplayRef.current = {
              maximumSequence: control.maximumSequence,
              ended: false,
            };
            protocolPhaseRef.current = "replaying";
            return;
          }
          case "replay_truncated": {
            const acceptedReplay = acceptedReplayRef.current;
            if (
              protocolPhaseRef.current !== "replaying" ||
              acceptedReplay === null ||
              !acceptedReplay.truncated ||
              control.minimumSequence !== acceptedReplay.minimumSequence
            ) {
              failSocket(socket);
              return;
            }
            acceptedReplay.truncationSeen = true;
            setReplayTruncated(true);
            return;
          }
          case "replay_end": {
            const acceptedReplay = acceptedReplayRef.current;
            const activeReplay = activeReplayRef.current;
            if (
              protocolPhaseRef.current !== "replaying" ||
              acceptedReplay === null ||
              activeReplay === null ||
              control.maximumSequence !== activeReplay.maximumSequence ||
              highestOutputScheduledRef.current !== control.maximumSequence ||
              (acceptedReplay.truncated && !acceptedReplay.truncationSeen)
            ) {
              failSocket(socket);
              return;
            }
            activeReplay.ended = true;
            finishReplay(socket, generation);
            return;
          }
          case "input_ack":
            if (control.sequence >= nextInputSequenceRef.current) {
              failSocket(socket);
              return;
            }
            removePendingInputThrough(control.sequence);
            return;
          case "status":
            if (control.lifecycle === "terminating") {
              setConnection({ type: "terminating" });
            }
            return;
          case "heartbeat_ack":
            return;
          case "exit":
            terminateRequestedRef.current = false;
            intentionalSocketsRef.current.add(socket);
            inputEnabledRef.current = false;
            setConnection({ type: "exited" });
            closeSocket(socket);
            return;
          case "revoked":
            terminateRequestedRef.current = false;
            intentionalSocketsRef.current.add(socket);
            inputEnabledRef.current = false;
            setConnection({ type: "revoked" });
            closeSocket(socket);
            return;
          case "error":
            intentionalSocketsRef.current.add(socket);
            inputEnabledRef.current = false;
            setConnection({ type: "error" });
            closeSocket(socket);
            return;
        }
      };

      socket.onclose = () => {
        if (socketRef.current === socket) {
          socketRef.current = null;
        }
        if (socketGenerationRef.current === generation) {
          protocolPhaseRef.current = "closed";
          inputEnabledRef.current = false;
          clearHeartbeatTimer();
          clearOutputAckTimer();
        }
        if (!intentionalSocketsRef.current.has(socket)) {
          scheduleReconnect();
        }
      };
      socket.onerror = () => closeSocket(socket);
    } catch {
      if (attempt === connectAttemptRef.current) {
        setConnection({ type: "error" });
        scheduleReconnect();
      }
    } finally {
      if (attempt === connectAttemptRef.current) {
        connectInFlightRef.current = false;
      }
    }
  }, [
    clearHeartbeatTimer,
    clearOutputAckTimer,
    clearReconnectTimer,
    failSocket,
    finishReplay,
    queueOutputAcknowledgement,
    removePendingInputThrough,
    resource,
    scheduleReconnect,
    ticketMutation,
  ]);
  connectRef.current = () => void connect();

  const sendInputText = useCallback(
    (text: string): void => {
      const socket = socketRef.current;
      if (
        socket?.readyState !== WebSocket.OPEN ||
        protocolPhaseRef.current !== "live" ||
        !inputEnabledRef.current
      ) {
        return;
      }
      const chunks = splitTerminalInput(new TextEncoder().encode(text));
      for (const chunk of chunks) {
        if (
          pendingInputBytesRef.current + chunk.byteLength >
          MAX_PENDING_INPUT_BYTES
        ) {
          failSocket(socket);
          return;
        }
        const sequence = nextInputSequenceRef.current;
        nextInputSequenceRef.current += 1;
        pendingInputRef.current.set(sequence, chunk);
        pendingInputBytesRef.current += chunk.byteLength;
        try {
          socket.send(encodeTerminalInputFrame(sequence, chunk));
        } catch {
          closeSocket(socket);
          return;
        }
      }
    },
    [failSocket],
  );
  sendInputTextRef.current = sendInputText;

  const disposeTerminal = useCallback((): void => {
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    terminalRef.current?.dispose();
    terminalRef.current = null;
    fitRef.current = null;
  }, []);

  const hostRef = useCallback(
    (node: HTMLDivElement | null): void => {
      hostNodeRef.current = node;
      if (node === null) {
        disposeTerminal();
        return;
      }
      if (terminalRef.current !== null) {
        disposeTerminal();
      }
      const terminal = new Terminal({
        cursorBlink: true,
        convertEol: false,
        fontFamily:
          "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        fontSize: 13,
        scrollback: 5_000,
      });
      const fit = new FitAddon();
      terminal.loadAddon(fit);
      terminal.open(node);
      terminal.onData((data) => sendInputTextRef.current(data));
      terminalRef.current = terminal;
      fitRef.current = fit;
      resizeObserverRef.current = new ResizeObserver(() => fitAndResize());
      resizeObserverRef.current.observe(node);
      fit.fit();
    },
    [disposeTerminal, fitAndResize],
  );

  useEffect(() => {
    if (resourceKeyRef.current === resourceKey) {
      return;
    }
    resourceKeyRef.current = resourceKey;
    activatedRef.current = false;
    terminateRequestedRef.current = false;
    connectAttemptRef.current += 1;
    connectInFlightRef.current = false;
    clearReconnectTimer();
    clearHeartbeatTimer();
    clearOutputAckTimer();
    clearResizeTimer();
    const socket = socketRef.current;
    socketRef.current = null;
    if (socket !== null) {
      intentionalSocketsRef.current.add(socket);
      closeSocket(socket);
    }
    terminalRef.current?.reset();
    terminalIdRef.current = null;
    pendingInputRef.current.clear();
    pendingInputBytesRef.current = 0;
    nextInputSequenceRef.current = 1;
    acceptedNextInputSequenceRef.current = 1;
    highestOutputScheduledRef.current = 0;
    highestOutputRenderedRef.current = 0;
    protocolPhaseRef.current = "closed";
    inputEnabledRef.current = false;
    presentationRef.current = "collapsed";
    setPresentation("collapsed");
    setConnection({ type: "idle" });
    setReplayTruncated(false);
    setHasNewOutput(false);
  }, [
    clearHeartbeatTimer,
    clearOutputAckTimer,
    clearReconnectTimer,
    clearResizeTimer,
    resourceKey,
  ]);

  useEffect(() => {
    const state = projectionQuery.data?.state ?? null;
    if (state === "ended") {
      if (terminateRequestedRef.current) {
        terminateRequestedRef.current = false;
      }
      setConnection({ type: "exited" });
      return;
    }
    if (activatedRef.current && isTerminalProjectionReconnectable(state)) {
      void connect();
      return;
    }
    if (shouldRestoreChatForTerminalProjection(state)) {
      const socket = socketRef.current;
      if (socket !== null) {
        intentionalSocketsRef.current.add(socket);
        socketRef.current = null;
        closeSocket(socket);
      }
      inputEnabledRef.current = false;
      protocolPhaseRef.current = "closed";
      clearHeartbeatTimer();
      clearOutputAckTimer();
      clearReconnectTimer();
      presentationRef.current = "collapsed";
      setPresentation("collapsed");
      setConnection({ type: "idle" });
    }
  }, [
    clearHeartbeatTimer,
    clearOutputAckTimer,
    clearReconnectTimer,
    connect,
    projectionQuery.data?.state,
  ]);

  useEffect(() => {
    mountedRef.current = true;
    const intentionalSockets = intentionalSocketsRef.current;
    return () => {
      mountedRef.current = false;
      connectAttemptRef.current += 1;
      clearReconnectTimer();
      clearHeartbeatTimer();
      clearOutputAckTimer();
      clearResizeTimer();
      const socket = socketRef.current;
      if (socket !== null) {
        intentionalSockets.add(socket);
        closeSocket(socket);
      }
      disposeTerminal();
      dockResizeCleanupRef.current?.();
    };
  }, [
    clearHeartbeatTimer,
    clearOutputAckTimer,
    clearReconnectTimer,
    clearResizeTimer,
    disposeTerminal,
  ]);

  const activate = (next: RuntimeTerminalPresentation): void => {
    activatedRef.current = true;
    const resolved = mobile ? "focused" : next;
    presentationRef.current = resolved;
    setPresentation(resolved);
    setHasNewOutput(false);
    window.setTimeout(() => {
      fitAndResize();
      terminalRef.current?.focus();
      void connect();
    }, 0);
  };

  const sendSoftwareKey = (key: string): void => {
    const data = applyTerminalKeyModifiers(key, ctrlActive, altActive);
    sendInputText(data);
    setCtrlActive(false);
    setAltActive(false);
  };

  const resizeDock = (next: number): void => {
    setDockHeight(Math.min(MAX_DOCK_HEIGHT, Math.max(MIN_DOCK_HEIGHT, next)));
    window.requestAnimationFrame(fitAndResize);
  };

  const onDockResizeStart = (clientY: number): void => {
    const initialHeight = dockHeight;
    const onMove = (event: PointerEvent): void => {
      resizeDock(initialHeight + clientY - event.clientY);
    };
    const cleanup = (): void => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", cleanup);
      dockResizeCleanupRef.current = null;
    };
    dockResizeCleanupRef.current?.();
    dockResizeCleanupRef.current = cleanup;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", cleanup, { once: true });
  };

  return {
    projection: projectionQuery.data ?? null,
    projectionLoading: projectionQuery.isLoading,
    presentation,
    connection,
    replayTruncated,
    hasNewOutput,
    ctrlActive,
    altActive,
    hostRef,
    onExpand: () => activate("docked"),
    onFocus: () => activate("focused"),
    onCollapse: () => {
      presentationRef.current = "collapsed";
      setPresentation("collapsed");
    },
    onReturnToDock: () => {
      const next = mobile ? "collapsed" : "docked";
      presentationRef.current = next;
      setPresentation(next);
    },
    onTerminate: () => {
      terminateRequestedRef.current = true;
      const socket = socketRef.current;
      if (
        socket?.readyState === WebSocket.OPEN &&
        protocolPhaseRef.current === "live"
      ) {
        requestTerminate(socket);
        return;
      }
      activatedRef.current = true;
      setConnection({ type: "reconnecting" });
      void projectionQuery.refetch().then(() => connectRef.current());
    },
    onRetry: () => {
      terminateRequestedRef.current = false;
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket !== null) {
        intentionalSocketsRef.current.add(socket);
        closeSocket(socket);
      }
      connectAttemptRef.current += 1;
      connectInFlightRef.current = false;
      clearReconnectTimer();
      setConnection({ type: "reconnecting" });
      void projectionQuery.refetch().then(() => connectRef.current());
    },
    onToggleCtrl: () => setCtrlActive((current) => !current),
    onToggleAlt: () => setAltActive((current) => !current),
    onSoftwareKey: sendSoftwareKey,
    onFocusKeyboard: () => terminalRef.current?.focus(),
    dockHeight,
    onDockResizeStart,
    onDockResizeBy: (delta) => resizeDock(dockHeight + delta),
  };
}
