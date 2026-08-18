import { createServerContext } from "./context";
/**
 * Server-side tRPC Caller
 * - Called directly from Server Components without a network request
 */
import { createCallerFactory } from "./init";
import { appRouter } from "./routers/_app";

const createCaller = createCallerFactory(appRouter);

/**
 * tRPC caller for use in Server Components
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
