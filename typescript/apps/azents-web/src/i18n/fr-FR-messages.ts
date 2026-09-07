import account from "../../messages/fr-FR/account.json";
import agentWorkspacePicker from "../../messages/fr-FR/agentWorkspacePicker.json";
import appBar from "../../messages/fr-FR/appBar.json";
import auth from "../../messages/fr-FR/auth.json";
import chat from "../../messages/fr-FR/chat.json";
import common from "../../messages/fr-FR/common.json";
import elevation from "../../messages/fr-FR/elevation.json";
import externalChannelApproval from "../../messages/fr-FR/externalChannelApproval.json";
import landing from "../../messages/fr-FR/landing.json";
import memberProfile from "../../messages/fr-FR/memberProfile.json";
import metadata from "../../messages/fr-FR/metadata.json";
import oauth from "../../messages/fr-FR/oauth.json";
import oauthCallback from "../../messages/fr-FR/oauthCallback.json";
import runtimeLifecycle from "../../messages/fr-FR/runtimeLifecycle.json";
import runtimeMetrics from "../../messages/fr-FR/runtimeMetrics.json";
import security from "../../messages/fr-FR/security.json";
import skills from "../../messages/fr-FR/skills.json";
import workspace from "../../messages/fr-FR/workspace.json";
import workspaces from "../../messages/fr-FR/workspaces.json";
import { composeMessages } from "./message-composition";
import type enUSMessages from "./en-US-messages";

const messages = composeMessages([
  ["account", account],
  ["agentWorkspacePicker", agentWorkspacePicker],
  ["appBar", appBar],
  ["auth", auth],
  ["chat", chat],
  ["common", common],
  ["elevation", elevation],
  ["externalChannelApproval", externalChannelApproval],
  ["landing", landing],
  ["memberProfile", memberProfile],
  ["metadata", metadata],
  ["oauth", oauth],
  ["oauthCallback", oauthCallback],
  ["runtimeLifecycle", runtimeLifecycle],
  ["runtimeMetrics", runtimeMetrics],
  ["security", security],
  ["skills", skills],
  ["workspace", workspace],
  ["workspaces", workspaces],
]);

messages satisfies typeof enUSMessages;

export default messages;
