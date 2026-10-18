"use client";

import { Badge, Box, Divider, Stack, Text } from "@mantine/core";
import { useFormatter, useTranslations } from "next-intl";
import type {
  RoutineContentView,
  RoutineToolDetail,
  RoutineToolRequest,
  RoutineToolResult,
  RoutineWorkView,
} from "../routineToolPresentation";

function ContentFields({
  content,
}: {
  content: Partial<RoutineContentView>;
}): React.ReactElement {
  const t = useTranslations("routines");
  return (
    <Stack
      gap="xs"
      style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
    >
      {Object.keys(content).length === 0 && (
        <Text size="sm" c="dimmed">
          {t("tool.noChanges")}
        </Text>
      )}
      {content.title != null && (
        <Box>
          <Text size="xs" c="dimmed">
            {t("tool.routineTitle")}
          </Text>
          <Text size="sm">{content.title}</Text>
        </Box>
      )}
      {content.objective != null && (
        <Box>
          <Text size="xs" c="dimmed">
            {t("objective")}
          </Text>
          <Text size="sm">{content.objective}</Text>
        </Box>
      )}
      {content.sources != null && (
        <Box>
          <Text size="xs" c="dimmed">
            {t("sources")}
          </Text>
          <Text size="sm">
            {content.sources.length === 0 ? t("noSources") : t("manualSource")}
          </Text>
        </Box>
      )}
    </Stack>
  );
}

function WorkFields({ work }: { work: RoutineWorkView }): React.ReactElement {
  const t = useTranslations("routines");
  return (
    <Stack
      gap="xs"
      style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
    >
      <Badge
        variant="light"
        color={work.objective_outcome === "failed" ? "red" : "gray"}
      >
        {t(`outcomes.${work.objective_outcome}`)}
      </Badge>
      <Box>
        <Text size="xs" c="dimmed">
          {t("result")}
        </Text>
        <Text size="sm">{work.result}</Text>
      </Box>
      <Box>
        <Text size="xs" c="dimmed">
          {t("nextHint")}
        </Text>
        <Text size="sm">{work.next_hint}</Text>
      </Box>
      <Box>
        <Text size="xs" c="dimmed">
          {t("notification")}
        </Text>
        <Text size="sm">{work.notify ? t("notifyYes") : t("notifyNo")}</Text>
      </Box>
      {work.notify && work.message !== null && (
        <Box>
          <Text size="xs" c="dimmed">
            {t("message")}
          </Text>
          <Text size="sm">{work.message}</Text>
        </Box>
      )}
    </Stack>
  );
}

function RequestFields({
  request,
}: {
  request: RoutineToolRequest | null;
}): React.ReactElement {
  const t = useTranslations("routines");
  if (request === null) {
    return (
      <Text size="sm" c="dimmed">
        {t("tool.argumentsPending")}
      </Text>
    );
  }
  switch (request.type) {
    case "createRoutine":
      return <ContentFields content={request.content} />;
    case "listRoutines":
      return (
        <Text size="sm" c="dimmed">
          {t("tool.sessionInventory")}
        </Text>
      );
    case "updateRoutine":
      return (
        <Stack gap="md">
          <Text size="xs" fw={600}>
            {t("tool.previousContent")}
          </Text>
          <ContentFields content={request.expected} />
          <Text size="xs" fw={600}>
            {t("tool.requestedChanges")}
          </Text>
          <ContentFields content={request.changes} />
        </Stack>
      );
    case "recordRoutineResult":
      return (
        <Stack gap="xs">
          <Text size="xs" c="dimmed">
            {request.slug} · {request.executionId}
          </Text>
          <WorkFields work={request.work} />
        </Stack>
      );
    case "readRoutineContext":
      return (
        <Text size="sm" style={{ overflowWrap: "anywhere" }}>
          {request.slug} · {request.executionId}
        </Text>
      );
    case "inspectRoutine":
      return (
        <Text size="sm" style={{ overflowWrap: "anywhere" }}>
          {request.slug} ·{" "}
          {t("tool.recordLimit", { count: request.recordLimit })}
        </Text>
      );
    case "deleteRoutine":
      return (
        <Text size="sm" style={{ overflowWrap: "anywhere" }}>
          {request.slug}
        </Text>
      );
  }
}

function ResultFields({
  result,
}: {
  result: RoutineToolResult;
}): React.ReactElement {
  const t = useTranslations("routines");
  const formatter = useFormatter();
  switch (result.type) {
    case "definition":
      return (
        <Stack gap="xs">
          <Text size="xs" c="dimmed" style={{ overflowWrap: "anywhere" }}>
            {result.definition.slug}
          </Text>
          <ContentFields content={result.definition.content} />
        </Stack>
      );
    case "inventory":
      return result.items.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t("tool.emptyInventory")}
        </Text>
      ) : (
        <Stack gap="md">
          {result.items.map((item) => (
            <Box key={item.id}>
              <Text size="xs" c="dimmed" style={{ overflowWrap: "anywhere" }}>
                {item.slug}
              </Text>
              <ContentFields content={item.content} />
            </Box>
          ))}
        </Stack>
      );
    case "inspection":
      return result.detail === null ? (
        <Text size="sm" c="dimmed">
          {t("tool.notFound")}
        </Text>
      ) : (
        <Stack gap="md">
          <ContentFields content={result.detail.definition.content} />
          <Text size="sm" fw={500}>
            {t("records", { count: result.detail.records.length })}
          </Text>
          {result.detail.records.length === 0 && (
            <Text size="sm" c="dimmed">
              {t("noRecords")}
            </Text>
          )}
          {result.detail.records.map((record) => (
            <Box component="details" key={record.id}>
              <Box component="summary" style={{ cursor: "pointer" }}>
                <Text component="span" size="sm">
                  {formatter.dateTime(new Date(record.completed_at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </Text>
              </Box>
              <Stack gap="xs" mt="xs">
                <WorkFields work={record.work} />
                <Text size="sm">
                  {t("delivery")}:{" "}
                  {t(`deliveryStates.${record.delivery_status}`)}
                </Text>
                {record.delivery_error !== null && (
                  <Text size="sm" c="red">
                    {record.delivery_error}
                  </Text>
                )}
              </Stack>
            </Box>
          ))}
        </Stack>
      );
    case "context":
      return (
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            {t("tool.admittedContext")}
          </Text>
          <ContentFields content={result.context.candidate.content} />
          <Text size="xs" c="dimmed">
            {t("tool.sourceEvents")}
          </Text>
          {result.context.candidate.events.map((event, index) => (
            <Text key={`${event.observed_at}:${index}`} size="sm">
              {t("manualSource")} ·{" "}
              {formatter.dateTime(new Date(event.observed_at), {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </Text>
          ))}
          <Text size="sm">
            {t("admittedAt")}:{" "}
            {formatter.dateTime(new Date(result.context.admitted_at), {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </Text>
          {result.context.candidate.latest_work !== null && (
            <>
              <Text size="xs" c="dimmed">
                {t("tool.previousWork")}
              </Text>
              <WorkFields work={result.context.candidate.latest_work} />
            </>
          )}
        </Stack>
      );
    case "completion":
      return (
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            {result.created
              ? t("tool.newCompletion")
              : t("tool.existingCompletion")}
          </Text>
          <WorkFields work={result.execution.work} />
          <Box>
            <Text size="xs" c="dimmed">
              {t("delivery")}
            </Text>
            <Text size="sm">
              {t(`deliveryStates.${result.execution.delivery_status}`)}
            </Text>
            {result.execution.delivery_error !== null && (
              <Text size="sm" c="red" style={{ overflowWrap: "anywhere" }}>
                {result.execution.delivery_error}
              </Text>
            )}
          </Box>
        </Stack>
      );
  }
}

export function RoutineToolDetails({
  detail,
}: {
  detail: RoutineToolDetail;
}): React.ReactElement {
  const t = useTranslations("routines");
  return (
    <Stack gap="sm" style={{ minWidth: 0, overflowWrap: "anywhere" }}>
      <Text size="xs" fw={600}>
        {t("tool.requested")}
      </Text>
      <RequestFields request={detail.request} />
      {detail.outcome.type === "PENDING" ? (
        <Text size="sm" c="dimmed">
          {t("tool.resultPending")}
        </Text>
      ) : detail.outcome.type === "UNSUCCEEDED" ? (
        <Text size="sm" c="dimmed">
          {t("tool.noObservedResult")}
        </Text>
      ) : (
        <>
          <Divider />
          <Text size="xs" fw={600}>
            {t("tool.observedResult")}
          </Text>
          <ResultFields result={detail.outcome.result} />
        </>
      )}
    </Stack>
  );
}
