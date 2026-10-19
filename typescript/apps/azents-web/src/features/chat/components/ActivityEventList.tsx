import { Stack } from "@mantine/core";
import { ProviderToolCallCardContainer } from "../containers/ProviderToolCallCardContainer";
import { ToolCallCardContainer } from "../containers/ToolCallCardContainer";
import { ActivityMessageRow } from "./ActivityMessageRow";
import { ReasoningActivityRow } from "./ReasoningActivityRow";
import { SkillLoadedActivityRow } from "./SkillLoadedActivityRow";
import type { ActivityEvent } from "@azents/session-core/toolActivityPresentation";
import type { ReactElement } from "react";

/** Shared event dispatch inside a Run; grouping and lifecycle remain upstream. */
export function ActivityEventRow({
  event,
}: {
  event: ActivityEvent;
}): ReactElement | null {
  if (event.kind === "tool" && event.toolCall) {
    return event.toolCall.type === "client" ? (
      <ToolCallCardContainer toolCall={event.toolCall.toolCall} />
    ) : (
      <ProviderToolCallCardContainer toolCall={event.toolCall.toolCall} />
    );
  }
  if (event.kind === "reasoning") {
    return (
      <ReasoningActivityRow
        reasoningSummary={
          event.message?.reasoningSummary ?? event.message?.content ?? ""
        }
      />
    );
  }
  if (event.kind === "skill") {
    return (
      <SkillLoadedActivityRow
        content={event.message?.content ?? ""}
        name={event.message?.metadata?.name ?? null}
      />
    );
  }
  return <ActivityMessageRow event={event} />;
}

export function ActivityEventList({
  events,
}: {
  events: ActivityEvent[];
}): ReactElement {
  return (
    <Stack gap={0} data-chat-activity-events>
      {events.map((event) => (
        <ActivityEventRow key={event.id} event={event} />
      ))}
    </Stack>
  );
}
