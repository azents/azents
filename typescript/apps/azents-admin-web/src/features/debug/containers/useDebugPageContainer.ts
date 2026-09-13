"use client";

import { useState } from "react";

import { trpc } from "@/trpc/client";
import type {
  DebugExceptionState,
  DebugLogLevel,
  DebugLogState,
} from "../types";

export interface DebugPageContainerOutput {
  logLevel: DebugLogLevel;
  logMessage: string;
  exceptionMessage: string;
  logState: DebugLogState;
  exceptionState: DebugExceptionState;
  onLogLevelChange: (value: string | null) => void;
  onLogMessageChange: (value: string) => void;
  onExceptionMessageChange: (value: string) => void;
  onFireLog: () => void;
  onFireException: () => void;
}

function isDebugLogLevel(value: string): value is DebugLogLevel {
  return value === "warning" || value === "error" || value === "critical";
}

export function useDebugPageContainer(): DebugPageContainerOutput {
  const [logLevel, setLogLevel] = useState<DebugLogLevel>("error");
  const [logMessage, setLogMessage] = useState("Debug test log from admin web");
  const [exceptionMessage, setExceptionMessage] = useState(
    "Debug test exception from admin web",
  );

  const fireLog = trpc.debug.fireLog.useMutation();
  const fireException = trpc.debug.fireException.useMutation();

  const logState: DebugLogState = fireLog.isPending
    ? { type: "SUBMITTING" }
    : fireLog.isError
      ? { type: "ERROR", message: fireLog.error.message }
      : fireLog.isSuccess
        ? {
            type: "SUCCESS",
            level: logLevel,
            message: fireLog.data.message,
            sentryEventId: fireLog.data.sentry_event_id,
            sentryInitialized: fireLog.data.sentry.initialized,
            sentryDsnConfigured: fireLog.data.sentry.dsn_configured,
          }
        : { type: "IDLE" };

  const exceptionState: DebugExceptionState = fireException.isPending
    ? { type: "SUBMITTING" }
    : fireException.isError
      ? { type: "EXPECTED_ERROR" }
      : { type: "IDLE" };

  return {
    logLevel,
    logMessage,
    exceptionMessage,
    logState,
    exceptionState,
    onLogLevelChange: (value) => {
      if (value !== null && isDebugLogLevel(value)) {
        setLogLevel(value);
      }
    },
    onLogMessageChange: setLogMessage,
    onExceptionMessageChange: setExceptionMessage,
    onFireLog: () => fireLog.mutate({ level: logLevel, message: logMessage }),
    onFireException: () => fireException.mutate({ message: exceptionMessage }),
  };
}
