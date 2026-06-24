"use client";

import {
  Badge,
  Box,
  Center,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import type { VerificationDetailComponentProps } from "../containers/useVerificationDetailContainer";

/**
 * 날짜/시간 포맷팅 헬퍼
 */
function formatDateTime(isoString: string): string {
  return new Date(isoString).toLocaleString();
}

/**
 * Verification 상세 뷰 컴포넌트
 *
 * ADT 상태에 따라 적절한 UI를 렌더링합니다.
 * 읽기 전용 — 폼 없음.
 */
export function VerificationDetailView({
  state,
}: VerificationDetailComponentProps): React.ReactElement {
  switch (state.type) {
    case "EMPTY":
      return (
        <Center h="100%">
          <Text c="dimmed">인증 레코드를 선택하세요.</Text>
        </Center>
      );
    case "LOADING":
      return (
        <Center h="100%">
          <Loader />
        </Center>
      );
    case "ERROR":
      return (
        <Center h="100%">
          <Text c="red">에러: {state.message}</Text>
        </Center>
      );
    case "LOADED": {
      const v = state.verification;
      return (
        <Box p="md">
          <Stack gap="md">
            <Title order={5}>인증 상세</Title>
            <Table>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Th w={120}>ID</Table.Th>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {v.id}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>이메일</Table.Th>
                  <Table.Td>{v.email}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>인증 코드</Table.Th>
                  <Table.Td>
                    <Text ff="monospace" fw={600}>
                      {v.code}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>CSRF 토큰</Table.Th>
                  <Table.Td>
                    <Text size="xs" ff="monospace" truncate>
                      {v.csrf_token}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>상태</Table.Th>
                  <Table.Td>
                    {v.verified_at ? (
                      <Badge color="green" variant="light">
                        인증됨
                      </Badge>
                    ) : (
                      <Badge color="gray" variant="light">
                        대기중
                      </Badge>
                    )}
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>만료 시각</Table.Th>
                  <Table.Td>{formatDateTime(v.expires_at)}</Table.Td>
                </Table.Tr>
                {v.verified_at ? (
                  <Table.Tr>
                    <Table.Th>인증 시각</Table.Th>
                    <Table.Td>{formatDateTime(v.verified_at)}</Table.Td>
                  </Table.Tr>
                ) : null}
                <Table.Tr>
                  <Table.Th>생성 시각</Table.Th>
                  <Table.Td>{formatDateTime(v.created_at)}</Table.Td>
                </Table.Tr>
              </Table.Tbody>
            </Table>
          </Stack>
        </Box>
      );
    }
  }
}
