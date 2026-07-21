/**
 * WorkspaceMember tRPC 라우터
 *
 * azents admin API 서버와 서버사이드 통신하여 WorkspaceUser(멤버) 관리 기능을 제공합니다.
 * Generated client (@azents/admin-client)를 사용합니다.
 */
import {
  workspaceuserV1CreateWorkspaceUser,
  workspaceuserV1DeleteWorkspaceUser,
  workspaceuserV1GetWorkspaceUser,
  workspaceuserV1ListWorkspaceUsers,
  workspaceuserV1UpdateWorkspaceUser,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

// --- Input Schemas ---
const WorkspaceMemberCreateInput = z.object({
  workspace_handle: z.string(),
  user_id: z.string(),
  name: z.string().min(1).max(100),
  role: z.enum(["owner", "manager", "member"]),
});

const WorkspaceMemberUpdateInput = z.object({
  workspace_user_id: z.string(),
  name: z.string().min(1).max(100).optional(),
});

// --- Router ---
export const workspaceMemberRouter = router({
  /**
   * Workspace별 멤버 목록 조회
   */
  listByWorkspace: protectedProcedure
    .input(z.object({ workspace_handle: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await workspaceuserV1ListWorkspaceUsers({
        client: ctx.adminApiClient,
        path: { handle: input.workspace_handle },
        throwOnError: true,
      });

      return {
        items: data.items,
        total: data.items.length,
      };
    }),

  /**
   * WorkspaceUser 상세 조회
   */
  get: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await workspaceuserV1GetWorkspaceUser({
        client: ctx.adminApiClient,
        path: { workspace_user_id: input.id },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * WorkspaceUser 생성
   */
  create: protectedProcedure
    .input(WorkspaceMemberCreateInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await workspaceuserV1CreateWorkspaceUser({
        client: ctx.adminApiClient,
        body: input,
        throwOnError: true,
      });
      return data;
    }),

  /**
   * WorkspaceUser 수정
   */
  update: protectedProcedure
    .input(WorkspaceMemberUpdateInput)
    .mutation(async ({ ctx, input }) => {
      const { workspace_user_id, ...body } = input;
      const { data } = await workspaceuserV1UpdateWorkspaceUser({
        client: ctx.adminApiClient,
        path: { workspace_user_id },
        body,
        throwOnError: true,
      });
      return data;
    }),

  /**
   * WorkspaceUser 삭제
   */
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      await workspaceuserV1DeleteWorkspaceUser({
        client: ctx.adminApiClient,
        path: { workspace_user_id: input.id },
        throwOnError: true,
      });

      return { success: true };
    }),
});
