"use client";

import {
  Alert,
  Button,
  Container,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

interface RuntimeWebAuthProps {
  endpointId: string;
}

type AuthState = { type: "CHECKING" } | { type: "ERROR"; message: string };

async function responseError(response: Response): Promise<string> {
  const body: unknown = await response.json();
  if (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof body.error === "string"
  ) {
    return body.error;
  }
  return `Runtime Web authentication failed (${response.status}).`;
}

export function RuntimeWebAuth({
  endpointId,
}: RuntimeWebAuthProps): React.ReactElement {
  const t = useTranslations("runtimeWeb");
  const [state, setState] = useState<AuthState>({ type: "CHECKING" });

  useEffect(() => {
    let active = true;
    const start = async (): Promise<void> => {
      try {
        await fetch("/runtime-web/auth/probe", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phase: "reset" }),
        });
        document.cookie =
          "Azents-Runtime-Web-Cookie-Probe=ready; Path=/; SameSite=Strict; Secure";
        document.cookie =
          "__Http-Azents-Runtime-Web-Cookie-Probe=forged; Path=/; SameSite=Strict; Secure";
        const probe = await fetch("/runtime-web/auth/probe", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phase: "verify" }),
        });
        if (!probe.ok) {
          throw new Error(await responseError(probe));
        }
        const response = await fetch("/runtime-web/auth/start", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpointId }),
        });
        if (!response.ok) {
          throw new Error(await responseError(response));
        }
        const result: unknown = await response.json();
        if (
          typeof result !== "object" ||
          result === null ||
          !("mode" in result)
        ) {
          throw new Error(t("auth.invalidResponse"));
        }
        if (
          result.mode === "shared_cookie" &&
          "destination" in result &&
          typeof result.destination === "string"
        ) {
          window.location.assign(result.destination);
          return;
        }
        if (
          result.mode === "separate_domain" &&
          "brokerDestination" in result &&
          typeof result.brokerDestination === "string" &&
          "initiationId" in result &&
          typeof result.initiationId === "string"
        ) {
          const form = document.createElement("form");
          form.method = "POST";
          form.action = result.brokerDestination;
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "initiation_id";
          input.value = result.initiationId;
          form.append(input);
          document.body.append(form);
          form.submit();
          return;
        }
        throw new Error(t("auth.invalidResponse"));
      } catch (error) {
        if (active) {
          setState({
            type: "ERROR",
            message: error instanceof Error ? error.message : t("auth.failed"),
          });
        }
      }
    };
    void start();
    return () => {
      active = false;
    };
  }, [endpointId, t]);

  return (
    <Container size="xs" py="xl">
      <Paper withBorder radius="lg" p="xl">
        <Stack align="center" gap="md" ta="center">
          {state.type === "CHECKING" ? <Loader size="sm" /> : null}
          <Title order={1} size="h3">
            {t("auth.title")}
          </Title>
          <Text size="sm" c="dimmed">
            {state.type === "CHECKING"
              ? t("auth.description")
              : t("auth.errorDescription")}
          </Text>
          {state.type === "ERROR" ? (
            <>
              <Alert color="red" w="100%">
                {state.message}
              </Alert>
              <Button onClick={() => window.location.reload()}>
                {t("retry")}
              </Button>
            </>
          ) : null}
        </Stack>
      </Paper>
    </Container>
  );
}
