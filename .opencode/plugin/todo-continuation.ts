import type { Plugin } from "@opencode-ai/plugin";

const COUNTDOWN_MS = 2_000;
const COOLDOWN_MS = 5_000;
const MAX_CONSECUTIVE_CONTINUATIONS = 3;
const TERMINAL_STATUSES = new Set([
  "completed",
  "cancelled",
  "blocked",
  "deleted",
]);
const QUESTION_TOOL_NAMES = new Set(["question"]);

type Todo = {
  id?: string;
  content?: string;
  status?: string;
  priority?: string;
};

type MessagePart = {
  type?: string;
  name?: string;
  toolName?: string;
  text?: string;
};

type Message = {
  info?: {
    role?: string;
    error?: { name?: string };
  };
  role?: string;
  parts?: MessagePart[];
};

type EventProperties = Record<string, unknown> & {
  info?: { id?: string; sessionID?: string; role?: string };
  sessionID?: string;
  status?: { type?: string };
};

type SessionState = {
  timer?: ReturnType<typeof setTimeout>;
  lastInjectedAt?: number;
  consecutiveContinuations: number;
  abortDetected: boolean;
  injecting: boolean;
};

type SharedState = {
  sessions: Map<string, SessionState>;
};

const SHARED_STATE_KEY = Symbol.for("codingbot.todo-continuation.state");

type SessionClient = {
  todo(input: { path: { id: string } }): Promise<unknown>;
  messages(input: {
    path: { id: string };
    query?: { directory?: string };
  }): Promise<unknown>;
  promptAsync?(input: {
    path: { id: string };
    body: { parts: Array<{ type: "text"; text: string }> };
    query?: { directory?: string };
  }): Promise<unknown>;
  prompt(input: {
    path: { id: string };
    body: { parts: Array<{ type: "text"; text: string }> };
    query?: { directory?: string };
  }): Promise<unknown>;
};

const asArray = <T>(value: unknown): T[] => {
  if (Array.isArray(value)) return value as T[];
  if (typeof value === "object" && value !== null && "data" in value) {
    const data = (value as { data?: unknown }).data;
    if (Array.isArray(data)) return data as T[];
  }
  return [];
};

const isIncomplete = (todo: Todo): boolean => {
  const status = todo.status ?? "pending";
  return !TERMINAL_STATUSES.has(status);
};

const isAbortErrorName = (name: string | undefined): boolean =>
  name === "MessageAbortedError" || name === "AbortError";

const resolveSessionID = (
  properties: EventProperties | undefined,
): string | undefined =>
  properties?.sessionID ?? properties?.info?.sessionID ?? properties?.info?.id;

const hasPendingQuestionTool = (messages: Message[]): boolean => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const role = message?.info?.role ?? message?.role;

    if (role === "user") return false;
    if (role !== "assistant") continue;

    return (
      message.parts?.some((part) => {
        const isToolPart =
          part.type === "tool_use" || part.type === "tool-invocation";
        const toolName = part.name ?? part.toolName;
        return (
          isToolPart &&
          toolName !== undefined &&
          QUESTION_TOOL_NAMES.has(toolName)
        );
      }) ?? false
    );
  }
  return false;
};

const lastAssistantWasAborted = (messages: Message[]): boolean => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const role = message?.info?.role ?? message?.role;
    if (role !== "assistant") continue;
    return isAbortErrorName(message.info?.error?.name);
  }
  return false;
};

const getSharedState = (): SharedState => {
  const globalRecord = globalThis as typeof globalThis & {
    [SHARED_STATE_KEY]?: SharedState;
  };
  if (globalRecord[SHARED_STATE_KEY] === undefined) {
    globalRecord[SHARED_STATE_KEY] = { sessions: new Map() };
  }
  return globalRecord[SHARED_STATE_KEY];
};

const buildPrompt = (todos: Todo[]): string => {
  const incomplete = todos.filter(isIncomplete);
  const completedCount = todos.length - incomplete.length;
  const remaining = incomplete
    .map(
      (todo) =>
        `- [${todo.status ?? "pending"}] ${todo.content ?? "Untitled todo"}`,
    )
    .join("\n");

  return [
    "[SYSTEM REMINDER - TODO CONTINUATION]",
    "",
    "Incomplete tasks remain in your todo list. Continue working on the next pending task.",
    "",
    "- Proceed without asking for permission.",
    "- Mark each task complete when finished.",
    "- Do not stop until all tasks are completed, cancelled, or blocked.",
    "",
    `[Status: ${completedCount}/${todos.length} completed, ${incomplete.length} remaining]`,
    "",
    "Remaining tasks:",
    remaining,
  ].join("\n");
};

export const TodoContinuationPlugin: Plugin = async (ctx) => {
  console.log("[todo-continuation] loaded", { directory: ctx.directory });

  const states = getSharedState().sessions;
  const session = ctx.client.session as unknown as SessionClient;

  const getState = (sessionID: string): SessionState => {
    const existing = states.get(sessionID);
    if (existing) return existing;
    const state = {
      consecutiveContinuations: 0,
      abortDetected: false,
      injecting: false,
    };
    states.set(sessionID, state);
    return state;
  };

  const cancelTimer = (sessionID: string): void => {
    const state = states.get(sessionID);
    if (!state?.timer) return;
    clearTimeout(state.timer);
    state.timer = undefined;
  };

  const fetchTodos = async (sessionID: string): Promise<Todo[]> => {
    const response = await session.todo({ path: { id: sessionID } });
    return asArray<Todo>(response);
  };

  const fetchMessages = async (sessionID: string): Promise<Message[]> => {
    const response = await session.messages({
      path: { id: sessionID },
      query: { directory: ctx.directory },
    });
    return asArray<Message>(response);
  };

  const injectContinuation = async (sessionID: string): Promise<void> => {
    const state = getState(sessionID);
    state.timer = undefined;
    if (state.injecting) return;
    state.injecting = true;

    try {
      const todos = await fetchTodos(sessionID);
      const incompleteCount = todos.filter(isIncomplete).length;
      if (todos.length === 0 || incompleteCount === 0) {
        state.consecutiveContinuations = 0;
        return;
      }

      const now = Date.now();
      if (
        state.lastInjectedAt !== undefined &&
        now - state.lastInjectedAt < COOLDOWN_MS
      ) {
        return;
      }
      state.lastInjectedAt = now;
      state.consecutiveContinuations += 1;

      const input = {
        path: { id: sessionID },
        body: { parts: [{ type: "text" as const, text: buildPrompt(todos) }] },
        query: { directory: ctx.directory },
      };

      if (session.promptAsync) {
        await session.promptAsync(input);
        return;
      }
      await session.prompt(input);
    } finally {
      state.injecting = false;
    }
  };

  const handleIdle = async (sessionID: string): Promise<void> => {
    const state = getState(sessionID);
    if (state.abortDetected || state.timer) return;

    const now = Date.now();
    if (
      state.lastInjectedAt !== undefined &&
      now - state.lastInjectedAt < COOLDOWN_MS
    ) {
      return;
    }
    if (state.consecutiveContinuations >= MAX_CONSECUTIVE_CONTINUATIONS) {
      return;
    }

    const [todos, messages] = await Promise.all([
      fetchTodos(sessionID),
      fetchMessages(sessionID),
    ]);
    const incompleteCount = todos.filter(isIncomplete).length;
    if (todos.length === 0 || incompleteCount === 0) {
      state.consecutiveContinuations = 0;
      return;
    }
    if (lastAssistantWasAborted(messages) || hasPendingQuestionTool(messages)) {
      return;
    }

    state.timer = setTimeout(() => {
      void injectContinuation(sessionID).catch((error) => {
        console.warn(
          "[todo-continuation] Failed to inject continuation",
          error,
        );
      });
    }, COUNTDOWN_MS);
  };

  return {
    event: async ({ event }) => {
      const eventType = event.type as string;
      const properties = event.properties as EventProperties | undefined;
      const sessionID = resolveSessionID(properties);
      if (!sessionID) return;

      if (eventType === "session.deleted") {
        cancelTimer(sessionID);
        states.delete(sessionID);
        return;
      }

      if (eventType === "session.error") {
        cancelTimer(sessionID);
        const error = properties?.error as { name?: string } | undefined;
        const state = getState(sessionID);
        state.abortDetected = isAbortErrorName(error?.name);
        return;
      }

      if (
        eventType === "session.idle" ||
        (eventType === "session.status" && properties?.status?.type === "idle")
      ) {
        await handleIdle(sessionID);
        return;
      }

      if (
        eventType === "session.status" &&
        properties?.status?.type === "busy"
      ) {
        cancelTimer(sessionID);
        const state = getState(sessionID);
        state.abortDetected = false;
        state.consecutiveContinuations = 0;
        return;
      }

      if (
        eventType === "message.updated" ||
        eventType === "message.part.updated" ||
        eventType === "message.part.delta" ||
        eventType === "tool.execute.before" ||
        eventType === "tool.execute.after"
      ) {
        const state = getState(sessionID);
        state.abortDetected = false;

        if (
          eventType === "tool.execute.before" ||
          eventType === "tool.execute.after"
        ) {
          cancelTimer(sessionID);
          return;
        }

        if (
          eventType === "message.updated" &&
          properties?.info?.role === "user" &&
          (state.lastInjectedAt === undefined ||
            Date.now() - state.lastInjectedAt > COUNTDOWN_MS)
        ) {
          cancelTimer(sessionID);
          state.consecutiveContinuations = 0;
        }
      }
    },
    "tool.execute.before": async (input: { sessionID: string }) => {
      cancelTimer(input.sessionID);
    },
    "tool.execute.after": async (input: { sessionID: string }) => {
      cancelTimer(input.sessionID);
    },
  };
};
