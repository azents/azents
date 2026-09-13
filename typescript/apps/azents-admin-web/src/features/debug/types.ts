export type DebugLogLevel = "warning" | "error" | "critical";

export type DebugLogState =
  | { type: "IDLE" }
  | { type: "SUBMITTING" }
  | { type: "ERROR"; message: string }
  | {
      type: "SUCCESS";
      level: DebugLogLevel;
      message: string;
      sentryEventId: string | null;
      sentryInitialized: boolean;
      sentryDsnConfigured: boolean;
    };

export type DebugExceptionState =
  { type: "IDLE" } | { type: "SUBMITTING" } | { type: "EXPECTED_ERROR" };
