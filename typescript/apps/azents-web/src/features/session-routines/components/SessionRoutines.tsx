"use client";

import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Divider,
  Group,
  Loader,
  rem,
  ScrollArea,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import {
  IconArrowDown,
  IconArrowLeft,
  IconChevronRight,
  IconRefresh,
} from "@tabler/icons-react";
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
  viewportRef,
  refreshState,
  onSelect,
  onBack,
  onRefresh,
}: SessionRoutinesContainerOutput): React.ReactElement {
  const t = useTranslations("routines");
  return (
    <ScrollArea
      flex={1}
      mih={0}
      type="auto"
      viewportRef={viewportRef}
      viewportProps={{
        role: "region",
        "aria-label": t("inventory"),
        style: { overscrollBehaviorY: "contain" },
      }}
    >
      <Stack p="sm" gap="sm" className={classes.root}>
        {refreshState.type !== "IDLE" && (
          <Group
            gap="xs"
            justify="center"
            role={refreshState.type === "ERROR" ? "alert" : "status"}
          >
            {refreshState.type === "REFRESHING" ? (
              <Loader size="xs" />
            ) : (
              <IconArrowDown size={rem(14)} />
            )}
            <Text size="xs" c="dimmed">
              {refreshState.type === "ERROR"
                ? t("refreshError")
                : refreshState.type === "REFRESHING"
                  ? t("refreshing")
                  : refreshState.ready
                    ? t("releaseRefresh")
                    : t("pullRefresh")}
            </Text>
          </Group>
        )}
        <Group
          className={classes.intro}
          data-detail={selectedSlug !== null}
          justify="space-between"
          align="flex-start"
          wrap="nowrap"
        >
          <Text size="xs" c="dimmed">
            {t("description")}
          </Text>
          <ActionIcon
            variant="subtle"
            size="sm"
            aria-label={t("refresh")}
            className={classes.refresh}
            loading={refreshState.type === "REFRESHING"}
            onClick={() => void onRefresh()}
          >
            <IconRefresh size={rem(14)} />
          </ActionIcon>
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
              gap={0}
              className={classes.listPane}
            >
              {state.items.map((item) => (
                <UnstyledButton
                  key={item.id}
                  className={classes.item}
                  aria-pressed={selectedSlug === item.slug}
                  onClick={(event) => onSelect(item.slug, event.currentTarget)}
                >
                  <Group gap="xs" wrap="nowrap">
                    <Box miw={0} flex={1}>
                      <Text size="sm" fw={500} lineClamp={2}>
                        {item.content.title}
                      </Text>
                      <Text size="xs" c="dimmed" lineClamp={2} mt={rem(2)}>
                        {item.content.objective}
                      </Text>
                    </Box>
                    <IconChevronRight
                      aria-hidden="true"
                      size={rem(16)}
                      style={{ flexShrink: 0 }}
                    />
                  </Group>
                </UnstyledButton>
              ))}
            </Stack>
            <Stack gap="sm" className={classes.detailPane}>
              {selectedSlug !== null && (
                <Group
                  component="header"
                  gap="xs"
                  wrap="nowrap"
                  className={classes.detailHeader}
                >
                  <ActionIcon
                    hiddenFrom="sm"
                    variant="subtle"
                    aria-label={t("back")}
                    onClick={onBack}
                  >
                    <IconArrowLeft size={rem(18)} />
                  </ActionIcon>
                  <Title
                    order={5}
                    ref={detailHeading}
                    tabIndex={-1}
                    className={classes.prose}
                  >
                    {selectedTitle}
                  </Title>
                  <ActionIcon
                    hiddenFrom="sm"
                    variant="subtle"
                    size="sm"
                    aria-label={t("refresh")}
                    className={classes.refresh}
                    loading={refreshState.type === "REFRESHING"}
                    onClick={() => void onRefresh()}
                    ml="auto"
                  >
                    <IconRefresh size={rem(14)} />
                  </ActionIcon>
                </Group>
              )}
              <DetailState state={detail} />
            </Stack>
          </Box>
        )}
      </Stack>
    </ScrollArea>
  );
}
