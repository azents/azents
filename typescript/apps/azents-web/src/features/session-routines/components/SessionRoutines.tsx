"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useFormatter, useTranslations } from "next-intl";
import classes from "./SessionRoutines.module.css";
import type { SessionRoutinesContainerOutput } from "../containers/useSessionRoutinesContainer";
import type { RoutineDetailState } from "../types";
import type {
  RoutineDetailResponse,
  RoutineWorkRecordResponse,
} from "@azents/public-client";

function WorkRecord({
  record,
}: {
  record: RoutineWorkRecordResponse;
}): React.ReactElement {
  const t = useTranslations("routines");
  const formatter = useFormatter();
  return (
    <Box component="details" className={classes.record}>
      <Box component="summary" className={classes.recordSummary}>
        <Text component="span" size="sm" fw={500}>
          {formatter.dateTime(new Date(record.completed_at), {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        </Text>{" "}
        <Badge
          size="sm"
          variant="light"
          color={record.work.objective_outcome === "failed" ? "red" : "gray"}
        >
          {t(`outcomes.${record.work.objective_outcome}`)}
        </Badge>
      </Box>
      <Stack gap="sm" mt="sm">
        <Box>
          <Text size="xs" c="dimmed">
            {t("result")}
          </Text>
          <Text className={classes.prose} size="sm">
            {record.work.result}
          </Text>
        </Box>
        <Box>
          <Text size="xs" c="dimmed">
            {t("nextHint")}
          </Text>
          <Text className={classes.prose} size="sm">
            {record.work.next_hint}
          </Text>
        </Box>
        <Box>
          <Text size="xs" c="dimmed">
            {t("notification")}
          </Text>
          <Text size="sm">
            {record.work.notify ? t("notifyYes") : t("notifyNo")}
          </Text>
        </Box>
        {record.work.notify && record.work.message !== null && (
          <Box>
            <Text size="xs" c="dimmed">
              {t("message")}
            </Text>
            <Text className={classes.prose} size="sm">
              {record.work.message}
            </Text>
          </Box>
        )}
        <Box>
          <Text size="xs" c="dimmed">
            {t("delivery")}
          </Text>
          <Text size="sm">{t(`deliveryStates.${record.delivery_status}`)}</Text>
          {record.delivery_error !== null && (
            <Text size="sm" c="red" className={classes.prose}>
              {record.delivery_error}
            </Text>
          )}
        </Box>
      </Stack>
    </Box>
  );
}

function RoutineDetail({
  data,
}: {
  data: RoutineDetailResponse;
}): React.ReactElement {
  const t = useTranslations("routines");
  const formatter = useFormatter();
  const recentRecord = data.records[0] ?? null;
  return (
    <Stack gap="md">
      <Text size="xs" c="dimmed" className={classes.prose}>
        {data.routine.slug}
      </Text>
      <Box>
        <Text size="sm" fw={600}>
          {t("objective")}
        </Text>
        <Text size="sm" className={classes.prose}>
          {data.routine.content.objective}
        </Text>
      </Box>
      <Box>
        <Text size="sm" fw={600}>
          {t("sources")}
        </Text>
        <Text size="sm">
          {data.routine.content.sources.length === 0
            ? t("noSources")
            : t("manualSource")}
        </Text>
      </Box>
      <Box>
        <Text size="sm" fw={600}>
          {t("latestExecution")}
        </Text>
        {data.execution === null ? (
          <Text size="sm" c="dimmed">
            {recentRecord === null ? (
              t("notExecuted")
            ) : (
              <>
                {t("completedAt")}:{" "}
                {formatter.dateTime(new Date(recentRecord.completed_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </>
            )}
          </Text>
        ) : (
          <Stack gap="xs">
            <Badge variant="light" color="gray">
              {t(`phases.${data.execution.phase}`)}
            </Badge>
            <Text size="sm">
              {t("admittedAt")}:{" "}
              {formatter.dateTime(new Date(data.execution.admitted_at), {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </Text>
            {data.execution.started_at !== null && (
              <Text size="sm">
                {t("startedAt")}:{" "}
                {formatter.dateTime(new Date(data.execution.started_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </Text>
            )}
            {data.execution.completed_at !== null && (
              <Text size="sm">
                {t("completedAt")}:{" "}
                {formatter.dateTime(new Date(data.execution.completed_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </Text>
            )}
          </Stack>
        )}
      </Box>
      <Divider />
      <Text size="sm" fw={600}>
        {t("records", { count: data.records.length })}
      </Text>
      {data.records.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t("noRecords")}
        </Text>
      ) : (
        data.records.map((record) => (
          <WorkRecord key={record.id} record={record} />
        ))
      )}
    </Stack>
  );
}

function DetailState({
  state,
}: {
  state: RoutineDetailState;
}): React.ReactElement {
  const t = useTranslations("routines");
  switch (state.type) {
    case "NONE":
      return (
        <Text size="sm" c="dimmed">
          {t("selectRoutine")}
        </Text>
      );
    case "LOADING":
      return (
        <Group role="status">
          <Loader size="sm" />
          <Text size="sm">{t("loading")}</Text>
        </Group>
      );
    case "ERROR":
      return (
        <Alert color="red" title={t("unavailable")}>
          {state.message}
        </Alert>
      );
    case "LOADED":
      return <RoutineDetail data={state.data} />;
  }
}

export function SessionRoutines({
  state,
  detail,
  selectedSlug,
  selectedTitle,
  detailHeading,
  onSelect,
  onBack,
  onRefresh,
}: SessionRoutinesContainerOutput): React.ReactElement {
  const t = useTranslations("routines");
  return (
    <ScrollArea flex={1} mih={0} type="auto">
      <Stack p="md" gap="md" className={classes.root}>
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box style={{ minWidth: 0 }}>
            <Title order={3}>{t("title")}</Title>
            <Text size="sm" c="dimmed">
              {t("description")}
            </Text>
          </Box>
          <Button
            variant="subtle"
            size="compact-sm"
            onClick={onRefresh}
            style={{ flexShrink: 0 }}
          >
            {t("refresh")}
          </Button>
        </Group>
        {state.type === "LOADING" ? (
          <Group role="status">
            <Loader size="sm" />
            <Text size="sm">{t("loading")}</Text>
          </Group>
        ) : state.type === "ERROR" ? (
          <Alert color="red" title={t("unavailable")}>
            {state.message}
          </Alert>
        ) : state.items.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t("empty")}
          </Text>
        ) : (
          <Box className={classes.layout} data-selected={selectedSlug !== null}>
            <Stack
              component="nav"
              aria-label={t("inventory")}
              gap="xs"
              className={classes.listPane}
            >
              {state.items.map((item) => (
                <UnstyledButton
                  key={item.id}
                  className={classes.item}
                  aria-pressed={selectedSlug === item.slug}
                  onClick={(event) => onSelect(item.slug, event.currentTarget)}
                >
                  <Text size="sm" fw={500} className={classes.prose}>
                    {item.content.title}
                  </Text>
                  <Text size="xs" c="dimmed" className={classes.prose}>
                    {item.slug}
                  </Text>
                </UnstyledButton>
              ))}
            </Stack>
            <Stack gap="md" className={classes.detailPane}>
              {selectedSlug !== null && (
                <>
                  <Button
                    hiddenFrom="sm"
                    variant="subtle"
                    size="compact-sm"
                    onClick={onBack}
                    style={{ alignSelf: "flex-start" }}
                  >
                    {t("back")}
                  </Button>
                  <Title
                    order={4}
                    ref={detailHeading}
                    tabIndex={-1}
                    className={classes.prose}
                  >
                    {selectedTitle}
                  </Title>
                </>
              )}
              <DetailState state={detail} />
            </Stack>
          </Box>
        )}
      </Stack>
    </ScrollArea>
  );
}
