"use client";

/**
 * Step-up authentication view.
 *
 * Elevate with email OTP or password.
 * Render directly in main view instead of modal.
 */
import {
  Anchor,
  Button,
  Container,
  Loader,
  PasswordInput,
  PinInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconLock, IconMail } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import type { ElevationModalContainerProps } from "../containers/useElevationModal";

/** Timer expiration time (seconds) */
const CODE_EXPIRY_SECONDS = 10 * 60;

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function ElevationView({
  state,
  onSelectEmail,
  onSelectPassword,
  onSubmitEmailCode,
  onSubmitPassword,
  onResendCode,
}: ElevationModalContainerProps): React.ReactElement {
  const t = useTranslations("elevation");

  return (
    <Container size="sm" py="xl">
      <Title order={2} mb="lg">
        {t("title")}
      </Title>
      {state.type === "CHOOSE_METHOD" && (
        <ChooseMethod
          hasPassword={state.methods.some(
            (m) => m.type === "password" && m.enabled,
          )}
          onSelectEmail={onSelectEmail}
          onSelectPassword={onSelectPassword}
        />
      )}
      {state.type === "EMAIL_SENDING" && (
        <Stack align="center" py="xl">
          <Loader />
          <Text c="dimmed">{t("sendingCode")}</Text>
        </Stack>
      )}
      {(state.type === "EMAIL_CODE" || state.type === "EMAIL_VERIFYING") && (
        <EmailCodeStep
          sentAt={state.sentAt}
          error={state.type === "EMAIL_CODE" ? state.error : null}
          isPending={state.type === "EMAIL_VERIFYING"}
          onSubmit={onSubmitEmailCode}
          onResend={onResendCode}
        />
      )}
      {(state.type === "PASSWORD_INPUT" ||
        state.type === "PASSWORD_VERIFYING") && (
        <PasswordStep
          error={state.type === "PASSWORD_INPUT" ? state.error : null}
          isPending={state.type === "PASSWORD_VERIFYING"}
          onSubmit={onSubmitPassword}
        />
      )}
    </Container>
  );
}

/** Authentication method selection */
function ChooseMethod({
  hasPassword,
  onSelectEmail,
  onSelectPassword,
}: {
  hasPassword: boolean;
  onSelectEmail: () => void;
  onSelectPassword: () => void;
}): React.ReactElement {
  const t = useTranslations("elevation");

  return (
    <Stack gap="md">
      <Text c="dimmed" size="sm">
        {t("description")}
      </Text>
      <Button
        variant="default"
        leftSection={<IconMail size={18} />}
        onClick={onSelectEmail}
        fullWidth
        justify="start"
      >
        {t("methodEmail")}
      </Button>
      {hasPassword && (
        <Button
          variant="default"
          leftSection={<IconLock size={18} />}
          onClick={onSelectPassword}
          fullWidth
          justify="start"
        >
          {t("methodPassword")}
        </Button>
      )}
    </Stack>
  );
}

/** Email OTP input */
function EmailCodeStep({
  sentAt,
  error,
  isPending,
  onSubmit,
  onResend,
}: {
  sentAt: number;
  error: string | null;
  isPending: boolean;
  onSubmit: (code: string) => void;
  onResend: () => void;
}): React.ReactElement {
  const t = useTranslations("elevation");
  const [code, setCode] = useState("");
  const [remainingSeconds, setRemainingSeconds] = useState(() => {
    const elapsed = Math.floor((Date.now() - sentAt) / 1000);
    return Math.max(0, CODE_EXPIRY_SECONDS - elapsed);
  });

  useEffect(() => {
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

  const handleChange = useCallback((value: string) => {
    setCode(value.toUpperCase());
  }, []);

  const handleComplete = useCallback(
    (value: string) => {
      onSubmit(value);
    },
    [onSubmit],
  );

  const isExpired = remainingSeconds === 0;

  return (
    <Stack gap="md" align="center">
      <Title order={4}>{t("emailCodeHeadline")}</Title>
      <Text size="sm" c="dimmed">
        {t("emailCodeDescription")}
      </Text>

      <PinInput
        length={6}
        type={/^[A-Za-z0-9]*$/}
        size="lg"
        inputMode="text"
        value={code}
        onChange={handleChange}
        onComplete={handleComplete}
        disabled={isPending || isExpired}
        error={!!error || isExpired}
      />

      <Text size="sm" c={isExpired ? "red" : "dimmed"}>
        {isExpired
          ? t("codeExpired")
          : t("codeTimer", { time: formatTime(remainingSeconds) })}
      </Text>

      {error && (
        <Text size="sm" c="red">
          {error}
        </Text>
      )}

      <Button
        loading={isPending}
        disabled={code.length !== 6 || isExpired}
        onClick={() => onSubmit(code)}
        fullWidth
      >
        {t("verify")}
      </Button>

      <Anchor
        component="button"
        type="button"
        size="sm"
        c="dimmed"
        onClick={onResend}
        style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
      >
        {t("resendCode")}
      </Anchor>
    </Stack>
  );
}

/** Password input */
function PasswordStep({
  error,
  isPending,
  onSubmit,
}: {
  error: string | null;
  isPending: boolean;
  onSubmit: (password: string) => void;
}): React.ReactElement {
  const t = useTranslations("elevation");
  const [password, setPassword] = useState("");

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    if (password) {
      onSubmit(password);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="md">
        <Title order={4}>{t("passwordHeadline")}</Title>
        <Text size="sm" c="dimmed">
          {t("passwordDescription")}
        </Text>
        <PasswordInput
          name="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          error={error}
          disabled={isPending}
          autoFocus
        />
        <Button
          type="submit"
          loading={isPending}
          disabled={!password}
          fullWidth
        >
          {t("verify")}
        </Button>
      </Stack>
    </form>
  );
}
