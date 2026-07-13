/**
 * Workspace tRPC 라우터
 *
 * azents admin API 서버와 서버사이드 통신하여 워크스페이스 관리 기능을 제공합니다.
 * Generated client (@azents/admin-client)를 사용합니다.
 */
import {
  workspaceV1CreateWorkspace,
  workspaceV1DeleteWorkspace,
  workspaceV1GetWorkspace,
  workspaceV1ListWorkspaces,
  workspaceV1UpdateWorkspace,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

// --- Input Schemas ---
const WorkspaceCreateInput = z.object({
  name: z.string().min(1).max(100),
  handle: z.string().min(1).max(100),
});

const WorkspaceUpdateInput = z.object({
  handle: z.string(),
  name: z.string().min(1).max(100),
  new_handle: z.string().min(1).max(100),
});

// --- Router ---
export const workspaceRouter = router({
  /**
   * 워크스페이스 목록 조회
   */
  list: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await workspaceV1ListWorkspaces({
      client: ctx.adminApiClient,
      throwOnError: true,
    });
    return {
      items: data.items,
      total: data.items.length,
    };
  }),

  /**
   * 워크스페이스 상세 조회
   */
  get: protectedProcedure
    .input(z.object({ handle: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await workspaceV1GetWorkspace({
        client: ctx.adminApiClient,
        path: { handle: input.handle },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * 워크스페이스 생성
   */
  create: protectedProcedure
    .input(WorkspaceCreateInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await workspaceV1CreateWorkspace({
        client: ctx.adminApiClient,
        body: input,
        throwOnError: true,
      });
      return data;
    }),

  /**
   * 워크스페이스 수정
   */
  update: protectedProcedure
    .input(WorkspaceUpdateInput)
    .mutation(async ({ ctx, input }) => {
      const { handle, ...body } = input;
      const { data } = await workspaceV1UpdateWorkspace({
        client: ctx.adminApiClient,
        path: { handle },
        body: { name: body.name, handle: body.new_handle },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * 워크스페이스 삭제
   */
  delete: protectedProcedure
    .input(z.object({ handle: z.string() }))
    .mutation(async ({ ctx, input }) => {
      await workspaceV1DeleteWorkspace({
        client: ctx.adminApiClient,
        path: { handle: input.handle },
        throwOnError: true,
      });
      return { success: true };
    }),
});
