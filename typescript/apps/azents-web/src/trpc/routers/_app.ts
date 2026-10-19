/**
 * Root Router
 * - Combine all sub-routers
 */
import { router } from "../init";
import { accountLinksRouter } from "./account-links";
import { agentRouter } from "./agent";
import { authRouter } from "./auth";
import { browserRouter } from "./browser";
import { chatRouter } from "./chat";
import { externalChannelRouter } from "./externalChannel";
import { invitationRouter } from "./invitation";
import { joinRequestRouter } from "./joinRequest";
import { llmProviderIntegrationRouter } from "./llm-provider-integration";
import { memberProfileRouter } from "./member-profile";
import { personalToolkitRouter } from "./personal-toolkit";
import { routineRouter } from "./routine";
import { runtimeProfileRouter } from "./runtime-profile";
import { runtimeWebRouter } from "./runtime-web";
import { scheduledTaskRouter } from "./scheduledTask";
import { securityRouter } from "./security";
import { terminalRouter } from "./terminal";
import { toolkitRouter } from "./toolkit";
import { userRouter } from "./user";
import { workspaceRouter } from "./workspace";
import { workspaceMemberRouter } from "./workspace-member";
import { workspaceModelSettingsRouter } from "./workspace-model-settings";

export const appRouter = router({
  accountLinks: accountLinksRouter,
  agent: agentRouter,
  auth: authRouter,
  browser: browserRouter,
  chat: chatRouter,
  externalChannel: externalChannelRouter,
  invitation: invitationRouter,
  joinRequest: joinRequestRouter,
  llmProviderIntegration: llmProviderIntegrationRouter,
  memberProfile: memberProfileRouter,
  personalToolkit: personalToolkitRouter,
  routine: routineRouter,
  runtimeProfile: runtimeProfileRouter,
  runtimeWeb: runtimeWebRouter,
  scheduledTask: scheduledTaskRouter,
  security: securityRouter,
  toolkit: toolkitRouter,
  terminal: terminalRouter,
  user: userRouter,
  workspace: workspaceRouter,
  workspaceMember: workspaceMemberRouter,
  workspaceModelSettings: workspaceModelSettingsRouter,
});

// Type export for client
export type AppRouter = typeof appRouter;
