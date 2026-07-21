"use client";

import {
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import type { WorkspaceDetailComponentProps } from "../containers/useWorkspaceDetailContainer";

/**
 * Workspace 상세 뷰 컴포넌트
 *
 * ADT 상태에 따라 폼 또는 플레이스홀더를 렌더링합니다.
 */
export function WorkspaceDetailView({
  state,
  form,
  isDirty,
  onSubmit,
  onCancel,
}: WorkspaceDetailComponentProps): React.ReactElement {
  switch (state.type) {
    case "EMPTY":
      return (
        <Center h="100%">
          <Text c="dimmed">Workspace를 선택하거나 새로 생성하세요.</Text>
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

    case "EDITING":
    case "SAVING": {
      const isSaving = state.type === "SAVING";
      const isProcessing = isSaving;
      const isNew = state.isNew;
      const workspace = state.workspace;

      return (
        <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
          <form
            onSubmit={form.onSubmit(onSubmit)}
            style={{ display: "flex", flexDirection: "column", height: "100%" }}
          >
            <Group p="sm" justify="space-between">
              <Title order={5}>
                {isNew ? "Workspace 추가" : "Workspace 편집"}
              </Title>
              <Group gap="xs">
                <Button
                  variant="outline"
                  size="xs"
                  onClick={onCancel}
                  disabled={isProcessing}
                >
                  취소
                </Button>
                <Button
                  type="submit"
                  size="xs"
                  disabled={isProcessing || (!isNew && !isDirty)}
                  loading={isSaving}
                >
                  {isSaving ? "저장 중..." : "저장"}
                </Button>
              </Group>
            </Group>

            <Box style={{ flex: 1, overflow: "auto" }} p="md">
              <Stack gap="md">
                <TextInput
                  label="이름"
                  placeholder="Workspace 이름"
                  required
                  key={form.key("name")}
                  {...form.getInputProps("name")}
                />
                <TextInput
                  label="Handle"
                  placeholder="workspace-handle"
                  description="소문자, 숫자, 하이픈만 사용 가능합니다."
                  required
                  key={form.key("handle")}
                  {...form.getInputProps("handle")}
                />
                {workspace && !isNew && (
                  <Stack gap="xs">
                    <Text size="sm" c="dimmed">
                      생성일:{" "}
                      {dayjs(workspace.created_at).format(
                        "YYYY-MM-DD HH:mm:ss",
                      )}
                    </Text>
                    <Text size="sm" c="dimmed">
                      수정일:{" "}
                      {dayjs(workspace.updated_at).format(
                        "YYYY-MM-DD HH:mm:ss",
                      )}
                    </Text>
                  </Stack>
                )}
              </Stack>
            </Box>
          </form>
        </Box>
      );
    }
  }
}
