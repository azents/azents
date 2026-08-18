/**
 * Client-side tRPC
 * - Client hooks using React Query
 */
"use client";

import { createTRPCReact } from "@trpc/react-query";
import type { AppRouter } from "./routers/_app";

export const trpc = createTRPCReact<AppRouter>();
