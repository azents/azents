"use client";

/**
 * Onboarding step progress indicator.
 *
 * Visually distinguishes current/completed/future steps in horizontal layout.
 * Supports both light/dark modes using Mantine theme colors.
 */
import { Box, Group, rem, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";

interface StepIndicatorProps {
  currentStep: 1 | 2 | 3;
  totalSteps?: number;
}

export function StepIndicator({
  currentStep,
  totalSteps = 3,
}: StepIndicatorProps): React.ReactElement {
  return (
    <Group gap={0} justify="center">
      {Array.from({ length: totalSteps }, (_, i) => {
        const step = i + 1;
        const isCompleted = step < currentStep;
        const isCurrent = step === currentStep;

        return (
          <Group key={step} gap={0}>
            {/* Connector line (not shown before first step) */}
            {i > 0 && (
              <Box
                style={{
                  width: rem(32),
                  height: rem(1),
                  backgroundColor: isCompleted
                    ? "var(--mantine-color-text)"
                    : "var(--mantine-color-default-border)",
                }}
              />
            )}

            {/* Step display */}
            <Box
              style={{
                display: "flex",
                width: rem(28),
                height: rem(28),
                alignItems: "center",
                justifyContent: "center",
                borderRadius: "50%",
                ...(isCompleted
                  ? {
                      border: `${rem(2)} solid var(--mantine-color-text)`,
                      backgroundColor: "var(--mantine-color-text)",
                    }
                  : isCurrent
                    ? {
                        border: `${rem(2)} solid var(--mantine-color-text)`,
                        backgroundColor: "transparent",
                      }
                    : {
                        border: `${rem(1)} solid var(--mantine-color-default-border)`,
                        backgroundColor: "transparent",
                      }),
              }}
            >
              {isCompleted ? (
                <IconCheck
                  size={14}
                  color="var(--mantine-color-body)"
                  stroke={3}
                />
              ) : (
                <Text size="xs" fw={600} c={isCurrent ? "" : "dimmed"}>
                  {step}
                </Text>
              )}
            </Box>
          </Group>
        );
      })}
    </Group>
  );
}
