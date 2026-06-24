"use client";

/**
 * Verification code input component
 *
 * Features:
 * - 6-character uppercase letters + digits PinInput (auto-uppercase lowercase input)
 * - Paste support
 * - Resend code button (shows loading state)
 * - 10-minute expiration timer based on sentAt (persists across refresh/resend)
 */
import {
  Anchor,
  Button,
  Loader,
  PinInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { VerifyStepContainerProps } from "../containers/useVerifyStep";

/** Timer expiration time (seconds) */
const CODE_EXPIRY_SECONDS = 10 * 60;

/** Format as mm:ss */
function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Verification code input form (pure UI) */
function VerifyStepForm({
  email,
  sentAt,
  error,
  isPending,
  isResending,
  onSubmit,
  onResend,
}: {
  email: string;
  sentAt: number;
  error: string | null;
  isPending: boolean;
  isResending: boolean;
  onSubmit: (code: string) => void;
  onResend: () => void;
}): React.ReactElement {
  const t = useTranslations("auth");
  const [code, setCode] = useState("");
  const [remainingSeconds, setRemainingSeconds] = useState(() => {
    if (!sentAt) {
      return 0;
    }
    const elapsed = Math.floor((Date.now() - sentAt) / 1000);
    return Math.max(0, CODE_EXPIRY_SECONDS - elapsed);
  });

  /** Recalculate timer + reset code when sentAt changes */
  useEffect(() => {
    if (!sentAt) {
      return;
    }

    const calcRemaining = (): number => {
      const elapsed = Math.floor((Date.now() - sentAt) / 1000);
      return Math.max(0, CODE_EXPIRY_SECONDS - elapsed);
    };

    setRemainingSeconds(calcRemaining());
    setCode("");

    const timer = setInterval(() => {
      const remaining = calcRemaining();
      setRemainingSeconds(remaining);
      if (remaining <= 0) {
        clearInterval(timer);
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [sentAt]);

  const inputType = /^[A-Za-z0-9]*$/;

  const handleChange = useCallback((value: string) => {
    setCode(value.toUpperCase());
  }, []);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const pasted = e.clipboardData
      .getData("text")
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, "")
      .slice(0, 6);
    if (pasted.length > 0) {
      e.preventDefault();
      setCode(pasted);
    }
  }, []);

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    if (code.length === 6) {
      onSubmit(code);
    }
  }

  function handleComplete(value: string): void {
    onSubmit(value);
  }

  const isExpired = remainingSeconds === 0;

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
