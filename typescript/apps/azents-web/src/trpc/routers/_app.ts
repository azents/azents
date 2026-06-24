/**
 * Root Router
 * - Combine all sub-routers
 */
import { router } from "../init";
import { agentRouter } from "./agent";
import { agentSubagentRouter } from "./agentSubagent";
import { authRouter } from "./auth";
import { chatRouter } from "./chat";
import { githubPatRouter } from "./github-pat";
import { invitationRouter } from "./invitation";
import { joinRequestRouter } from "./joinRequest";
import { llmProviderIntegrationRouter } from "./llm-provider-integration";
import { memberProfileRouter } from "./member-profile";
import { passwordResetTokenAdminRouter } from "./password-reset-token-admin";
import { securityRouter } from "./security";
import { signupTokenAdminRouter } from "./signup-token-admin";
import { toolkitRouter } from "./toolkit";
import { userRouter } from "./user";
import { workspaceRouter } from "./workspace";
import { workspaceMemberRouter } from "./workspace-member";
import { workspaceModelSettingsRouter } from "./workspace-model-settings";

export const appRouter = router({
  agent: agentRouter,
  agentSubagent: agentSubagentRouter,
  auth: authRouter,
  chat: chatRouter,
  githubPat: githubPatRouter,
  invitation: invitationRouter,
  joinRequest: joinRequestRouter,
  llmProviderIntegration: llmProviderIntegrationRouter,
  memberProfile: memberProfileRouter,
  passwordResetTokenAdmin: passwordResetTokenAdminRouter,
  security: securityRouter,
  signupTokenAdmin: signupTokenAdminRouter,
  toolkit: toolkitRouter,
  user: userRouter,
  workspace: workspaceRouter,
  workspaceMember: workspaceMemberRouter,
  workspaceModelSettings: workspaceModelSettingsRouter,
});

// Type export for client
export type AppRouter = typeof appRouter;
