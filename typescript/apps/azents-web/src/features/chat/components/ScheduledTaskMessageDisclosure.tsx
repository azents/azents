"use client";

import { IconCalendarClock } from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import { scheduledTaskMessagePresentation } from "../scheduledTaskMessagePresentation";
import { AgentMessageDisclosure } from "./AgentMessageDisclosure";
import type { ChatMessage } from "../types";

interface ScheduledTaskMessageDisclosureProps {
  message: ChatMessage;
  actions?: React.ReactNode;
}

function formatInstant(
  value: string,
  locale: string,
  timeZone: string | null,
): string | null {
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
    ...(timeZone === null ? {} : { timeZone }),
  }).format(instant);
}

function scheduleTime(
  scheduledFor: string | null,
  locale: string,
  timeZone: string,
): string | null {
  if (scheduledFor === null) {
    return null;
  }
  const instant = new Date(scheduledFor);
  if (!Number.isFinite(instant.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(locale, {
    hour: "numeric",
    minute: "2-digit",
    timeZone,
    timeZoneName: "short",
  }).format(instant);
}

function localizedDayNames(values: string[], locale: string): string | null {
  const weekdays = [
    "2026-08-16T12:00:00Z",
    "2026-08-17T12:00:00Z",
    "2026-08-18T12:00:00Z",
    "2026-08-19T12:00:00Z",
    "2026-08-20T12:00:00Z",
    "2026-08-21T12:00:00Z",
    "2026-08-22T12:00:00Z",
  ];
  const names = values.flatMap((value) => {
    const index = Number(value === "7" ? "0" : value);
    const date = weekdays[index];
    return typeof date === "string"
      ? [
          new Intl.DateTimeFormat(locale, {
            weekday: "long",
            timeZone: "UTC",
          }).format(new Date(date)),
        ]
      : [];
  });
  if (names.length !== values.length) {
    return null;
  }
  return new Intl.ListFormat(locale, {
    style: "long",
    type: "conjunction",
  }).format(names);
}

function localizedCronSchedule(
  canonical: string,
  scheduledFor: string | null,
  locale: string,
  t: ReturnType<typeof useTranslations<"chat.scheduledTaskMessage">>,
): string | null {
  const match = /^(.+) \(([^()]+)\)$/u.exec(canonical);
  if (match === null) {
    return null;
  }
  const expression = match[1];
  const timeZone = match[2];
  if (typeof expression !== "string" || typeof timeZone !== "string") {
    return null;
  }
  const fields = expression.split(/\s+/u);
  if (fields.length !== 5) {
    return null;
  }
  const [minute, hour, dayOfMonth, month, dayOfWeek] = fields;
  if (expression === "* * * * *") {
    return t("recurrence.everyMinute", { timezone: timeZone });
  }
  const interval = /^\*\/(\d+)$/u.exec(minute ?? "");
  if (
    interval !== null &&
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return t("recurrence.everyMinutes", {
      count: Number(interval[1]),
      timezone: timeZone,
    });
  }
  if (
    /^\d+$/u.test(minute ?? "") &&
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return t("recurrence.hourly", {
      minute: String(Number(minute)),
      timezone: timeZone,
    });
  }
  if (
    !/^\d+$/u.test(minute ?? "") ||
    !/^\d+$/u.test(hour ?? "") ||
    dayOfMonth !== "*" ||
    month !== "*"
  ) {
    return t("recurrence.recurring", { timezone: timeZone });
  }
  const time = scheduleTime(scheduledFor, locale, timeZone);
  if (time === null) {
    return null;
  }
  const normalizedDays = dayOfWeek?.replaceAll("7", "0");
  if (normalizedDays === "*") {
    return t("recurrence.daily", { time });
  }
  if (normalizedDays === "1-5") {
    return t("recurrence.weekdays", { time });
  }
  if (normalizedDays === "0,6" || normalizedDays === "6,0") {
    return t("recurrence.weekends", { time });
  }
  const days = localizedDayNames(normalizedDays?.split(",") ?? [], locale);
  return days === null ? null : t("recurrence.weekly", { days, time });
}

export function ScheduledTaskMessageDisclosure({
  message,
  actions = null,
}: ScheduledTaskMessageDisclosureProps): React.ReactElement {
  const locale = useLocale();
  const t = useTranslations("chat.scheduledTaskMessage");
  const presentation = scheduledTaskMessagePresentation(message);
  const title = presentation.title ?? t("fallbackTitle");
  const canonical = presentation.scheduleCanonical;
  const cronTimezone =
    canonical === null
      ? null
      : (/^.+ \(([^()]+)\)$/u.exec(canonical)?.[1] ?? null);
  const schedule =
    canonical === null
      ? presentation.schedule
      : (localizedCronSchedule(
          canonical,
          presentation.scheduledForCanonical,
          locale,
          t,
        ) ??
        formatInstant(canonical, locale, null) ??
        presentation.schedule);
  const scheduledFor =
    presentation.scheduledForCanonical === null
      ? presentation.scheduledFor
      : (formatInstant(
          presentation.scheduledForCanonical,
          locale,
          cronTimezone,
        ) ?? presentation.scheduledFor);
  const content =
    presentation.prompt === null
      ? presentation.fallbackContent
      : [
          schedule === null ? null : `**${t("schedule")}**\n${schedule}`,
          scheduledFor === null
            ? null
            : `**${t("scheduledFor")}**\n${scheduledFor}`,
          canonical === null
            ? null
            : `**${t("scheduleDetails")}**\n\`${canonical}\``,
          `**${t("prompt")}**\n\n${presentation.prompt}`,
        ]
          .filter((value): value is string => value !== null)
          .join("\n\n");

  return (
    <AgentMessageDisclosure
      title={t("title", { title })}
      titleTooltip={title}
      content={content}
      actions={actions}
      icon={<IconCalendarClock aria-hidden="true" size={14} stroke={1.8} />}
    />
  );
}
