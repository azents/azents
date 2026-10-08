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
import type { RuntimeWebAuthState } from "../types";

interface RuntimeWebAuthProps {
  serviceId: string;
  mainWebOrigin: string | null;
  state: RuntimeWebAuthState;
  onRetry: () => void;
}

export function RuntimeWebAuth({
  serviceId,
  mainWebOrigin,
  state,
  onRetry,
}: RuntimeWebAuthProps): React.ReactElement {
  const t = useTranslations("runtimeWeb");

  return (
    <Container
      id="runtime-web-auth"
      size="xs"
      py="xl"
      data-service-id={serviceId}
      data-main-web-origin={mainWebOrigin ?? ""}
      data-invalid-response={t("auth.invalidResponse")}
      data-failed-message={t("auth.failed")}
    >
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
              <Button onClick={onRetry}>{t("retry")}</Button>
            </>
          ) : null}
        </Stack>
      </Paper>
    </Container>
  );
}
