"use client";

import { Alert, Button, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { modelAvailabilityRemainingMinutes } from "../modelAvailability";
import type { ModelAvailabilityViewState } from "../modelAvailability";

export interface ModelAvailabilityControlProps {
  state: ModelAvailabilityViewState;
  activeSemanticLabel: string;
  actionPending: boolean;
  actionError: boolean;
  observedAtMs: number;
  nowMs: number;
  onRefresh: () => Promise<void>;
  onReservePrimary: () => Promise<void>;
  onCancelPrimary: () => Promise<void>;
}

export function ModelAvailabilityControl({
  state,
  activeSemanticLabel,
  actionPending,
  actionError,
  observedAtMs,
  nowMs,
  onRefresh,
  onReservePrimary,
  onCancelPrimary,
}: ModelAvailabilityControlProps): React.ReactElement | null {
  const t = useTranslations("chat.composerProfile");
  if (state.type === "UNAVAILABLE") {
    return null;
  }
  if (state.type === "LOADING") {
    return (
      <Stack gap="xs">
        <Text size="xs" c="dimmed" fw={600}>
          {t("availabilityTitle")}
        </Text>
        <Text size="sm" c="dimmed">
          {t("availabilityLoading")}
        </Text>
      </Stack>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Stack gap="xs">
        <Text size="xs" c="dimmed" fw={600}>
          {t("availabilityTitle")}
        </Text>
        <Alert color="orange" title={t("availabilityError")}>
          <Stack gap="xs">
            <Text size="sm">{t("availabilityErrorDescription")}</Text>
            <Button
              size="compact-sm"
              variant="light"
              onClick={() => void onRefresh()}
            >
              {t("refreshAvailability")}
            </Button>
          </Stack>
        </Alert>
      </Stack>
    );
  }

  const availability = state.data;
  const matchesDraft = availability.semantic_label === activeSemanticLabel;
  const remainingMinutes = modelAvailabilityRemainingMinutes(
    availability,
    observedAtMs,
    nowMs,
  );
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed" fw={600}>
        {t("availabilityTitle")}
      </Text>
      {!matchesDraft ? (
        <Alert color="blue">{t("applyBeforeAvailability")}</Alert>
      ) : (
        <Alert
          color={
            availability.state === "available"
              ? "green"
              : availability.state === "primary_next"
                ? "blue"
                : "orange"
          }
          title={
            availability.state === "available"
              ? t("primaryAvailable", {
                  model: availability.primary_display_name,
                })
              : availability.state === "primary_next"
                ? t("primaryNextTitle", {
                    model: availability.primary_display_name,
                  })
                : availability.state === "probing"
                  ? t("primaryProbing", {
                      model: availability.primary_display_name,
                    })
                  : t("primaryCooldown", {
                      model: availability.primary_display_name,
                    })
          }
        >
          <Stack gap="xs">
            {availability.first_usable_fallback_display_name != null &&
            availability.state !== "available" &&
            availability.state !== "primary_next" ? (
              <Text size="sm">
                {t("currentFallback", {
                  model: availability.first_usable_fallback_display_name,
                })}
              </Text>
            ) : null}
            {remainingMinutes != null && availability.state !== "available" ? (
              <Text size="xs" c="dimmed">
                {t("availabilityDeadline", { minutes: remainingMinutes })}
              </Text>
            ) : null}
            {availability.state === "cooldown" ? (
              <Button
                size="compact-sm"
                variant="light"
                loading={actionPending}
                onClick={() => void onReservePrimary()}
              >
                {t("usePrimaryNext")}
              </Button>
            ) : availability.state === "primary_next" ? (
              <Button
                size="compact-sm"
                variant="light"
                color="gray"
                loading={actionPending}
                onClick={() => void onCancelPrimary()}
              >
                {t("cancelPrimaryNext")}
              </Button>
            ) : null}
            {actionError ? (
              <Text size="xs" c="red">
                {t("availabilityConflict")}
              </Text>
            ) : null}
          </Stack>
        </Alert>
      )}
    </Stack>
  );
}
