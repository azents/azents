import { createServerContext } from "./context";
/**
 * Server-side tRPC Caller
 * - Direct call from Server Component without network
 */
import { createCallerFactory } from "./init";
import { appRouter } from "./routers/_app";

const createCaller = createCallerFactory(appRouter);

/**
 * Server Component in use tRPC caller
 *
 * @example
 * ```tsx
 * import { trpc } from '@/trpc/server';
 *
 * export default async function Page() {
 *   const data = await trpc.workspace.list();
 *   return <VerifyResult data={data} />;
 * }
 * ```
 */
export const trpc = createCaller(createServerContext);
