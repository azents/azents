"use client";

import {
  Button,
  Center,
  Container,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconBrandGithub } from "@tabler/icons-react";
import type { LoginPageContainerOutput } from "../containers/useLoginPageContainer";

/**
 * 로그인 페이지 뷰 컴포넌트
 *
 * 순수 UI 렌더링만 담당합니다.
 */
export function LoginPageView({
  state,
  onLogin,
}: LoginPageContainerOutput): React.ReactElement {
  const isLoading = state.type === "LOADING";

  return (
    <Container size="sm" h="100vh">
      <Center h="100%">
        <Paper shadow="md" p="xl" w="100%">
          <Stack align="center" gap="md">
            <Title order={3}>Azents Admin</Title>
            <Text c="dimmed" ta="center" size="sm">
              GitHub 계정으로 로그인하여 Admin 패널에 접속합니다.
            </Text>
            {state.type === "ERROR" && (
              <Text c="red" size="sm">
                {state.message}
              </Text>
            )}
            <Button
              size="lg"
              leftSection={<IconBrandGithub size={20} />}
              onClick={onLogin}
              loading={isLoading}
            >
              GitHub으로 로그인
            </Button>
          </Stack>
        </Paper>
      </Center>
    </Container>
  );
}
