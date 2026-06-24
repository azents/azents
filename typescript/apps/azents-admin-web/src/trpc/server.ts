import { createServerContext } from "./context";
/**
 * Server-side tRPC Caller
 * - Server Component에서 네트워크 없이 직접 호출
 */
import { createCallerFactory } from "./init";
import { appRouter } from "./routers/_app";

const createCaller = createCallerFactory(appRouter);

/**
 * Server Component에서 사용할 tRPC caller
 *
 * @example
 * ```tsx
 * import { trpc } from '@/trpc/server';
 *
 * export default async function Page() {
 *   const data = await trpc.workspace.list();
 *   return <WorkspaceList data={data} />;
 * }
 * ```
 */
export const trpc = createCaller(createServerContext);
