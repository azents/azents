/**
 * Root Router
 * - 모든 서브 라우터를 통합
 */
import { router } from "../init";
import { debugRouter } from "./debug";
import { signupTokenRouter } from "./signupToken";
import { userRouter } from "./user";
import { userEmailRouter } from "./userEmail";
import { verificationRouter } from "./verification";
import { workspaceRouter } from "./workspace";
import { workspaceMemberRouter } from "./workspaceMember";

export const appRouter = router({
  debug: debugRouter,
  workspace: workspaceRouter,
  user: userRouter,
  userEmail: userEmailRouter,
  workspaceMember: workspaceMemberRouter,
  verification: verificationRouter,
  signupToken: signupTokenRouter,
});

// 클라이언트용 타입 export
export type AppRouter = typeof appRouter;
