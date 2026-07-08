/**
 * Root Router
 * - Combine all sub-routers
 */
import { router } from "../init";
import { agentRouter } from "./agent";
import { authRouter } from "./auth";
import { chatRouter } from "./chat";
import { invitationRouter } from "./invitation";
import { joinRequestRouter } from "./joinRequest";
import { llmProviderIntegrationRouter } from "./llm-provider-integration";
import { memberProfileRouter } from "./member-profile";
import { securityRouter } from "./security";
import { toolkitRouter } from "./toolkit";
import { userRouter } from "./user";
import { workspaceRouter } from "./workspace";
import { workspaceMemberRouter } from "./workspace-member";
import { workspaceModelSettingsRouter } from "./workspace-model-settings";

export const appRouter = router({
  agent: agentRouter,
  auth: authRouter,
  chat: chatRouter,
  invitation: invitationRouter,
  joinRequest: joinRequestRouter,
  llmProviderIntegration: llmProviderIntegrationRouter,
  memberProfile: memberProfileRouter,
  security: securityRouter,
  toolkit: toolkitRouter,
  user: userRouter,
  workspace: workspaceRouter,
  workspaceMember: workspaceMemberRouter,
  workspaceModelSettings: workspaceModelSettingsRouter,
});

// Type export for client
export type AppRouter = typeof appRouter;
