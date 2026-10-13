"use client";
import { Alert, Button, Container, Loader, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
export interface GoogleCallbackProps {
  state:
    | { type: "VERIFYING" }
    | {
        type: "ERROR";
        reason:
          | "staleCallback"
          | "cancelFailed"
          | "verificationUncertain"
          | "verificationFailed";
      };
  returnPath: string | null;
}
export function GoogleCallback({
  state,
  returnPath,
}: GoogleCallbackProps): React.ReactElement {
  const t = useTranslations("googleToolkit");
  return (
    <Container size="sm" py="xl">
      <Stack gap="md">
        {state.type === "VERIFYING" ? (
          <>
            <Loader />
            <Text role="status">{t("verifying")}</Text>
          </>
        ) : (
          <Alert color="yellow" role="alert">
            {t(state.reason)}
          </Alert>
        )}
        {returnPath != null && (
          <Button component={Link} href={returnPath}>
            {t("returnToSetup")}
          </Button>
        )}
      </Stack>
    </Container>
  );
}
