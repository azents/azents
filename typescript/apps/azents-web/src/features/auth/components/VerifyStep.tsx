"use client";
import {
  Anchor,
  Button,
  Loader,
  PinInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
/**
 * Verification code input component
 *
 * Features:
 * - 6-character uppercase letters + digits PinInput (auto-uppercase lowercase input)
 * - Paste support
 * - Resend code button (shows loading state)
 * - 10-minute expiration timer based on sentAt (persists across refresh/resend)
 */
import { FormPageLayout } from "@/shared/components/FormPageLayout";

import { useVerifyStepFormController } from "../containers/useVerifyStepFormController";
import type { VerifyStepContainerProps } from "../containers/useVerifyStep";
import type { VerifyStepFormViewProps } from "../containers/useVerifyStepFormController";

/** Format as mm:ss */
function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Verification code input form (pure UI) */
function VerifyStepForm(props: {
  email: string;
  sentAt: number;
  error: string | null;
  isPending: boolean;
  isResending: boolean;
  onSubmit: (code: string) => void;
  onResend: () => void;
}): React.ReactElement {
  return <VerifyStepFormView {...useVerifyStepFormController(props)} />;
}

export function VerifyStepFormView({
  email,
  error,
  isPending,
  isResending,
  onResend,
  t,
  code,
  remainingSeconds,
  inputType,
  handleChange,
  handlePaste,
  handleSubmit,
  handleComplete,
  isExpired,
}: VerifyStepFormViewProps): React.ReactElement {
  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="lg" align="center">
        <Stack gap="xs" align="center">
          <Title order={2}>{t("verifyStep.headline")}</Title>
          <Text c="dimmed">{t("verifyStep.description", { email })}</Text>
        </Stack>

        <div onPaste={handlePaste}>
          <PinInput
            length={6}
            type={inputType}
            size="lg"
            inputMode="text"
            autoCapitalize="characters"
            value={code}
            onChange={handleChange}
            onComplete={handleComplete}
            disabled={isPending || isExpired}
            error={!!error || isExpired}
          />
        </div>

        <Text size="sm" c={isExpired ? "red" : "dimmed"}>
          {isExpired
            ? t("verifyStep.expired")
            : t("verifyStep.timer", { time: formatTime(remainingSeconds) })}
        </Text>

        {error && (
          <Text size="sm" c="red">
            {error}
          </Text>
        )}

        <Button
          type="submit"
          size="lg"
          loading={isPending}
          disabled={code.length !== 6 || isExpired}
          fullWidth
        >
          {t("verifyStep.submit")}
        </Button>

        <Anchor
          component="button"
          type="button"
          size="sm"
          c="dimmed"
          onClick={onResend}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "var(--mantine-spacing-2xs)",
          }}
        >
          {isResending && <Loader size={12} />}
          {t("verifyStep.resend")}
        </Anchor>
      </Stack>
    </form>
  );
}

/** Container -> Component mapping (including FormPageLayout) */
export function VerifyStep({
  state,
  isResending,
  onSubmit,
  onResend,
}: VerifyStepContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      <VerifyStepForm
        email={state.email}
        sentAt={state.sentAt}
        error={state.type === "IDLE" ? state.error : null}
        isPending={state.type === "VERIFYING"}
        isResending={isResending}
        onSubmit={onSubmit}
        onResend={onResend}
      />
    </FormPageLayout>
  );
}
