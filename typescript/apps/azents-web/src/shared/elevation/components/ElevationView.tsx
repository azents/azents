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
  rem,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconLock, IconMail } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEmailCodeStepController } from "../containers/useEmailCodeStepController";
import { usePasswordStepController } from "../containers/usePasswordStepController";
import type { ElevationModalContainerProps } from "../containers/useElevationModal";
import type { EmailCodeStepViewProps } from "../containers/useEmailCodeStepController";
import type { PasswordStepViewProps } from "../containers/usePasswordStepController";

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
        leftSection={<IconMail size={rem(18)} />}
        onClick={onSelectEmail}
        fullWidth
        justify="start"
      >
        {t("methodEmail")}
      </Button>
      {hasPassword && (
        <Button
          variant="default"
          leftSection={<IconLock size={rem(18)} />}
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
function EmailCodeStep(props: {
  sentAt: number;
  error: string | null;
  isPending: boolean;
  onSubmit: (code: string) => void;
  onResend: () => void;
}): React.ReactElement {
  return <EmailCodeStepView {...useEmailCodeStepController(props)} />;
}

export function EmailCodeStepView({
  error,
  isPending,
  onSubmit,
  onResend,
  t,
  code,
  remainingSeconds,
  handleChange,
  handleComplete,
  isExpired,
}: EmailCodeStepViewProps): React.ReactElement {
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
        style={{ display: "inline-flex", alignItems: "center", gap: rem(4) }}
      >
        {t("resendCode")}
      </Anchor>
    </Stack>
  );
}

/** Password input */
function PasswordStep(props: {
  error: string | null;
  isPending: boolean;
  onSubmit: (password: string) => void;
}): React.ReactElement {
  return <PasswordStepView {...usePasswordStepController(props)} />;
}

export function PasswordStepView({
  error,
  isPending,
  t,
  password,
  setPassword,
  handleSubmit,
}: PasswordStepViewProps): React.ReactElement {
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
