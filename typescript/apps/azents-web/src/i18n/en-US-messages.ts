import account from "../../messages/en-US/account.json";
import agentWorkspacePicker from "../../messages/en-US/agentWorkspacePicker.json";
import appBar from "../../messages/en-US/appBar.json";
import auth from "../../messages/en-US/auth.json";
import chat from "../../messages/en-US/chat.json";
import common from "../../messages/en-US/common.json";
import elevation from "../../messages/en-US/elevation.json";
import externalChannelApproval from "../../messages/en-US/externalChannelApproval.json";
import landing from "../../messages/en-US/landing.json";
import memberProfile from "../../messages/en-US/memberProfile.json";
import metadata from "../../messages/en-US/metadata.json";
import oauth from "../../messages/en-US/oauth.json";
import oauthCallback from "../../messages/en-US/oauthCallback.json";
import runtimeLifecycle from "../../messages/en-US/runtimeLifecycle.json";
import runtimeMetrics from "../../messages/en-US/runtimeMetrics.json";
import security from "../../messages/en-US/security.json";
import skills from "../../messages/en-US/skills.json";
import workspace from "../../messages/en-US/workspace.json";
import workspaces from "../../messages/en-US/workspaces.json";
import { composeMessages } from "./message-composition";

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

export default messages;
