import type {
  ManagedBinding,
  ScheduledTaskCurrentCycleResponse,
  ScheduledTaskResponse,
} from "@azents/public-client";

export type ScheduledTasksState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; tasks: ScheduledTaskResponse[] };

export type ScheduledTaskDetailState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      task: ScheduledTaskResponse;
      cycle: ScheduledTaskCurrentCycleResponse | null;
      cycleLoading: boolean;
      cycleError: string | null;
    };

export interface ScheduledTaskDraft {
  sessionId: string;
  title: string;
  objective: string;
  scheduleType: "once" | "cron";
  at: string;
  cron: string;
  timezone: string;
  channelId: string | null;
}

export type ScheduledTaskFormError =
  | "sessionRequired"
  | "titleRequired"
  | "objectiveRequired"
  | "oneTimeRequired"
  | "oneTimeInvalid"
  | "cronRequired"
  | "timezoneRequired";

export type ScheduledTaskFormState =
  | { type: "CLOSED" }
  | {
      type: "CREATE" | "EDIT";
      taskId: string | null;
      draft: ScheduledTaskDraft;
      bindings: ManagedBinding[];
      bindingsLoading: boolean;
      bindingsError: string | null;
      error: ScheduledTaskFormError | null;
    };

export type ScheduledTaskActionError =
  | { type: "CONFLICT" }
  | { type: "ERROR"; message: string };
