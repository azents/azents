/**
 * Client-side tRPC
 * - React Query를 사용한 클라이언트 훅
 */
"use client";

import { createTRPCReact } from "@trpc/react-query";
import type { AppRouter } from "./routers/_app";

export const trpc = createTRPCReact<AppRouter>();
