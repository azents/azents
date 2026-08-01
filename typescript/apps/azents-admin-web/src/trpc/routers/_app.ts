/**
 * Root Router
 * - 모든 서브 라우터를 통합
 */
import { router } from "../init";
import { bootstrapRouter } from "./bootstrap";
import { debugRouter } from "./debug";
import { modelCatalogRouter } from "./modelCatalog";
import { retentionRouter } from "./retention";
import { runtimeProviderRouter } from "./runtimeProvider";
import { signupTokenRouter } from "./signupToken";
import { systemRoleRouter } from "./systemRole";
import { systemSettingsRouter } from "./systemSettings";
import { userRouter } from "./user";
import { userEmailRouter } from "./userEmail";
import { verificationRouter } from "./verification";
import { workspaceRouter } from "./workspace";
import { workspaceMemberRouter } from "./workspaceMember";

export const appRouter = router({
  bootstrap: bootstrapRouter,
  debug: debugRouter,
  workspace: workspaceRouter,
  user: userRouter,
  userEmail: userEmailRouter,
  workspaceMember: workspaceMemberRouter,
  verification: verificationRouter,
  signupToken: signupTokenRouter,
  modelCatalog: modelCatalogRouter,
  retention: retentionRouter,
  runtimeProvider: runtimeProviderRouter,
  systemRole: systemRoleRouter,
  systemSettings: systemSettingsRouter,
});

// 클라이언트용 타입 export
export type AppRouter = typeof appRouter;
