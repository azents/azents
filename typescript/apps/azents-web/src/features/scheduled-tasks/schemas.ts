import { z } from "zod/v4";
import type { ScheduledTaskDraft, ScheduledTaskFormError } from "./types";

const draftSchema = z
  .object({
    sessionId: z.string(),
    title: z.string().trim(),
    objective: z.string().trim(),
    scheduleType: z.enum(["once", "cron"]),
    at: z.string(),
    cron: z.string(),
    timezone: z.string(),
    channelId: z.string().min(1).nullable(),
  })
  .superRefine((value, context) => {
    if (value.sessionId.trim() === "") {
      context.addIssue({
        code: "custom",
        path: ["sessionId"],
        message: "sessionRequired",
      });
    }
    if (value.title.trim() === "") {
      context.addIssue({
        code: "custom",
        path: ["title"],
        message: "titleRequired",
      });
    }
    if (value.objective.trim() === "") {
      context.addIssue({
        code: "custom",
        path: ["objective"],
        message: "objectiveRequired",
      });
    }
    if (value.scheduleType === "once" && value.at.trim() === "") {
      context.addIssue({
        code: "custom",
        path: ["at"],
        message: "oneTimeRequired",
      });
    } else if (
      value.scheduleType === "once" &&
      Number.isNaN(new Date(value.at).getTime())
    ) {
      context.addIssue({
        code: "custom",
        path: ["at"],
        message: "oneTimeInvalid",
      });
    }
    if (value.scheduleType === "cron" && value.cron.trim() === "") {
      context.addIssue({
        code: "custom",
        path: ["cron"],
        message: "cronRequired",
      });
    }
    if (value.scheduleType === "cron" && value.timezone.trim() === "") {
      context.addIssue({
        code: "custom",
        path: ["timezone"],
        message: "timezoneRequired",
      });
    }
  });

export interface ScheduledTaskMutationValues {
  sessionId: string;
  title: string;
  objective: string;
  at: string | null;
  cron: string | null;
  timezone: string | null;
  channelId: string | null;
}

export type ScheduledTaskDraftResult =
  | { success: true; values: ScheduledTaskMutationValues }
  | { success: false; error: ScheduledTaskFormError };

function formErrorFromMessage(message: string): ScheduledTaskFormError {
  switch (message) {
    case "sessionRequired":
    case "titleRequired":
    case "objectiveRequired":
    case "oneTimeRequired":
    case "oneTimeInvalid":
    case "cronRequired":
    case "timezoneRequired":
      return message;
    default:
      return "objectiveRequired";
  }
}

export function parseScheduledTaskDraft(
  draft: ScheduledTaskDraft,
): ScheduledTaskDraftResult {
  const result = draftSchema.safeParse(draft);
  if (!result.success) {
    return {
      success: false,
      error: formErrorFromMessage(
        result.error.issues[0]?.message ?? "objectiveRequired",
      ),
    };
  }
  const value = result.data;
  return {
    success: true,
    values: {
      sessionId: value.sessionId,
      title: value.title.trim(),
      objective: value.objective.trim(),
      at:
        value.scheduleType === "once" ? new Date(value.at).toISOString() : null,
      cron: value.scheduleType === "cron" ? value.cron.trim() : null,
      timezone: value.scheduleType === "cron" ? value.timezone.trim() : null,
      channelId: value.channelId,
    },
  };
}

export function toLocalDateTimeInput(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const localDate = new Date(
    date.getTime() - date.getTimezoneOffset() * 60_000,
  );
  return localDate.toISOString().slice(0, 16);
}
