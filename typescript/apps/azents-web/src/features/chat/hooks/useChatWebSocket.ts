"use client";

/**
 * existing chat session WebSocket live subscription hook.
 *
 *  hook  WebSocket connection, subscription barrier, reconnect, buffering only is responsible..
 * received chat event  parent container  of managed live/history state reducer  with passes it..
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatEvent, ConnectionStatus } from "../types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isChatEventWire(value: unknown): value is ChatEvent {
  if (!isRecord(value)) {
    return false;
  }
  if (typeof value.type === "string") {
    return true;
  }
  return typeof value.kind === "string" && isRecord(value.payload);
}

/** reconnect settings */
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 5000;
const RECONNECT_MAX_ATTEMPTS = Infinity;
const RESUME_DRIFT_THRESHOLD_MS = 30_000;
const RESUME_PROBE_INTERVAL_MS = 10_000;
const RESUME_RESYNC_THROTTLE_MS = 1_000;

/** batch reload interval (30sec) */
const BATCH_RELOAD_INTERVAL = 30_000;

interface UseChatWebSocketOptions {
  /** WebSocket base URL */
  wsUrl: string | null;
  /** HMAC signature ticket (30sec valid) */
  ticket: string | null;
  /** session ID */
  sessionId: string | null;
  /** received chat event  parent state reducer  with pass */
  onEvent: (event: ChatEvent) => void;
  /** message reload callback (batch for reload) */
  onBatchReload?: () => boolean;
  /** session subscription ack received callback */
  onSubscribed?: () => void;
  /** auth error when ticket refresh request callback */
  onAuthError?: () => void;
  /** Buffering notify that live event was held instead of rendered immediately while buffering */
  onBufferedLiveEvent?: () => void;
}

interface UseChatWebSocketReturn {
  /** connection status */
  connectionStatus: ConnectionStatus;
  /** whether to buffer WS events during baseline resync */
  setBufferingLiveEvents: (buffering: boolean) => void;
  /** replay buffered WS events on baseline */
  replayBufferedLiveEvents: () => void;
  /** session subscription health check barrier */
  requestSubscriptionHealthCheck: () => Promise<boolean>;
}

export function useChatWebSocket({
  wsUrl,
  ticket,
  sessionId,
  onEvent,
  onBatchReload,
  onSubscribed,
  onAuthError,
  onBufferedLiveEvent,
}: UseChatWebSocketOptions): UseChatWebSocketReturn {
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("disconnected");

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const batchReloadTimerRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );
  const shouldReconnectRef = useRef(true);
  const isBufferingLiveEventsRef = useRef(false);
  const liveEventBufferRef = useRef<ChatEvent[]>([]);
  const healthCheckWaitersRef = useRef<Map<string, (success: boolean) => void>>(
    new Map(),
  );
  const resumeResyncInFlightRef = useRef(false);
  const lastResumeResyncAtRef = useRef(0);
  const resumeProbeLastTickAtRef = useRef(Date.now());

  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onBatchReloadRef = useRef(onBatchReload);
  onBatchReloadRef.current = onBatchReload;
  const onSubscribedRef = useRef(onSubscribed);
  onSubscribedRef.current = onSubscribed;
  const onAuthErrorRef = useRef(onAuthError);
  onAuthErrorRef.current = onAuthError;
  const onBufferedLiveEventRef = useRef(onBufferedLiveEvent);
  onBufferedLiveEventRef.current = onBufferedLiveEvent;

  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (batchReloadTimerRef.current) {
      clearInterval(batchReloadTimerRef.current);
      batchReloadTimerRef.current = null;
    }
  }, []);

  const setBufferingLiveEvents = useCallback((buffering: boolean): void => {
    isBufferingLiveEventsRef.current = buffering;
    if (buffering) {
      liveEventBufferRef.current = [];
    }
  }, []);

  const replayBufferedLiveEvents = useCallback((): void => {
    const buffered = liveEventBufferRef.current;
    liveEventBufferRef.current = [];
    isBufferingLiveEventsRef.current = false;
    for (const event of buffered) {
      onEventRef.current(event);
    }
  }, []);

  const requestSubscriptionHealthCheck = useCallback((): Promise<boolean> => {
    const ws = wsRef.current;
    if (ws === null || ws.readyState !== WebSocket.OPEN) {
      return Promise.resolve(false);
    }
    const requestId = crypto.randomUUID();
    return new Promise((resolve) => {
      const timeout = window.setTimeout(() => {
        healthCheckWaitersRef.current.delete(requestId);
        resolve(false);
      }, 5000);
      healthCheckWaitersRef.current.set(requestId, (success) => {
        window.clearTimeout(timeout);
        resolve(success);
      });
      ws.send(
        JSON.stringify({
          type: "subscription_health_check",
          session_id: sessionIdRef.current,
          request_id: requestId,
        }),
      );
    });
  }, []);

  const connect = useCallback(() => {
    if (!wsUrl || !ticket || sessionIdRef.current === null) {
      return;
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    setConnectionStatus(
      reconnectAttemptRef.current > 0 ? "reconnecting" : "connecting",
    );

    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const currentSessionId = sessionIdRef.current;
    const sessionPath = encodeURIComponent(currentSessionId);
    const url = `${wsUrl}/chat/v1/sessions/${sessionPath}?ticket=${encodeURIComponent(ticket)}&timezone=${encodeURIComponent(tz)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionStatus(
        reconnectAttemptRef.current > 0 ? "reconnecting" : "connecting",
      );
    };

    ws.onmessage = (e: MessageEvent) => {
      if (typeof e.data !== "string") {
        return;
      }
      try {
        const raw: unknown = JSON.parse(e.data);
        if (!isChatEventWire(raw)) {
          return;
        }
        if ("type" in raw && raw.type === "subscribed") {
          setConnectionStatus("connected");
          reconnectAttemptRef.current = 0;
          if (batchReloadTimerRef.current) {
            clearInterval(batchReloadTimerRef.current);
          }
          batchReloadTimerRef.current = setInterval(() => {
            onBatchReloadRef.current?.();
          }, BATCH_RELOAD_INTERVAL);
          onSubscribedRef.current?.();
          return;
        }
        if ("type" in raw && raw.type === "subscription_health_check_ack") {
          const requestId = raw.request_id;
          if (typeof requestId === "string") {
            healthCheckWaitersRef.current.get(requestId)?.(true);
            healthCheckWaitersRef.current.delete(requestId);
          }
          return;
        }
        if (isBufferingLiveEventsRef.current) {
          liveEventBufferRef.current = [...liveEventBufferRef.current, raw];
          onBufferedLiveEventRef.current?.();
          return;
        }
        onEventRef.current(raw);
      } catch {
        console.error("WebSocket message parsing failed:", e.data);
      }
    };

    ws.onclose = (e: CloseEvent) => {
      if (wsRef.current !== ws) {
        return;
      }
      wsRef.current = null;

      if (batchReloadTimerRef.current) {
        clearInterval(batchReloadTimerRef.current);
        batchReloadTimerRef.current = null;
      }
      for (const resolve of healthCheckWaitersRef.current.values()) {
        resolve(false);
      }
      healthCheckWaitersRef.current.clear();

      if (e.code === 4001 || e.code === 4003) {
        setConnectionStatus("reconnecting");
        onAuthErrorRef.current?.();
        return;
      }

      setConnectionStatus("disconnected");

      if (
        shouldReconnectRef.current &&
        reconnectAttemptRef.current < RECONNECT_MAX_ATTEMPTS
      ) {
        const delay = Math.min(
          RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttemptRef.current),
          RECONNECT_MAX_DELAY,
        );
        reconnectAttemptRef.current += 1;
        setConnectionStatus("reconnecting");
        reconnectTimerRef.current = setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {};
  }, [wsUrl, ticket]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    clearTimers();
    if (wsRef.current) {
      const ws = wsRef.current;
      ws.onopen = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.close();
      wsRef.current = null;
    }
    setConnectionStatus("disconnected");
  }, [clearTimers]);

  useEffect(() => {
    if (wsUrl && ticket) {
      shouldReconnectRef.current = true;
      reconnectAttemptRef.current = 0;
      connect();
    }
    return () => {
      disconnect();
    };
  }, [wsUrl, ticket, connect, disconnect]);

  const requestResumeResync = useCallback((): void => {
    if (!wsUrl || sessionIdRef.current === null) {
      return;
    }
    const now = Date.now();
    if (resumeResyncInFlightRef.current) {
      return;
    }
    if (now - lastResumeResyncAtRef.current < RESUME_RESYNC_THROTTLE_MS) {
      return;
    }
    resumeResyncInFlightRef.current = true;
    lastResumeResyncAtRef.current = now;

    void requestSubscriptionHealthCheck()
      .then((ok) => {
        if (ok) {
          const reloadStarted = onBatchReloadRef.current?.() ?? false;
          if (!reloadStarted) {
            replayBufferedLiveEvents();
          }
          return;
        }
        replayBufferedLiveEvents();
        shouldReconnectRef.current = true;
        reconnectAttemptRef.current = 0;
        setConnectionStatus("reconnecting");
        onAuthErrorRef.current?.();
      })
      .finally(() => {
        resumeResyncInFlightRef.current = false;
      });
  }, [replayBufferedLiveEvents, requestSubscriptionHealthCheck, wsUrl]);

  useEffect(() => {
    const handleVisibilityChange = (): void => {
      if (document.visibilityState === "visible") {
        requestResumeResync();
      }
    };
    const handlePageShow = (): void => {
      requestResumeResync();
    };
    const handleFocus = (): void => {
      requestResumeResync();
    };
    const handleOnline = (): void => {
      requestResumeResync();
    };
    const handleResumeProbe = (): void => {
      const now = Date.now();
      const drift = now - resumeProbeLastTickAtRef.current;
      resumeProbeLastTickAtRef.current = now;
      if (drift > RESUME_DRIFT_THRESHOLD_MS) {
        requestResumeResync();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pageshow", handlePageShow);
    window.addEventListener("focus", handleFocus);
    window.addEventListener("online", handleOnline);
    const resumeProbeTimer = window.setInterval(
      handleResumeProbe,
      RESUME_PROBE_INTERVAL_MS,
    );
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pageshow", handlePageShow);
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener("online", handleOnline);
      window.clearInterval(resumeProbeTimer);
    };
  }, [requestResumeResync]);

  return {
    connectionStatus,
    setBufferingLiveEvents,
    replayBufferedLiveEvents,
    requestSubscriptionHealthCheck,
  };
}
