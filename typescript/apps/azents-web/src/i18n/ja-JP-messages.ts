import account from "../../messages/ja-JP/account.json";
import agentWorkspacePicker from "../../messages/ja-JP/agentWorkspacePicker.json";
import appBar from "../../messages/ja-JP/appBar.json";
import auth from "../../messages/ja-JP/auth.json";
import chat from "../../messages/ja-JP/chat.json";
import common from "../../messages/ja-JP/common.json";
import elevation from "../../messages/ja-JP/elevation.json";
import externalAccountLinks from "../../messages/ja-JP/externalAccountLinks.json";
import externalChannelApproval from "../../messages/ja-JP/externalChannelApproval.json";
import memberProfile from "../../messages/ja-JP/memberProfile.json";
import metadata from "../../messages/ja-JP/metadata.json";
import oauth from "../../messages/ja-JP/oauth.json";
import oauthCallback from "../../messages/ja-JP/oauthCallback.json";
import runtimeLifecycle from "../../messages/ja-JP/runtimeLifecycle.json";
import runtimeMetrics from "../../messages/ja-JP/runtimeMetrics.json";
import runtimeWeb from "../../messages/ja-JP/runtimeWeb.json";
import security from "../../messages/ja-JP/security.json";
import skills from "../../messages/ja-JP/skills.json";
import workspace from "../../messages/ja-JP/workspace.json";
import workspaces from "../../messages/ja-JP/workspaces.json";
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
  ["externalAccountLinks", externalAccountLinks],
  ["externalChannelApproval", externalChannelApproval],
  ["memberProfile", memberProfile],
  ["metadata", metadata],
  ["oauth", oauth],
  ["oauthCallback", oauthCallback],
  ["runtimeLifecycle", runtimeLifecycle],
  ["runtimeMetrics", runtimeMetrics],
  ["runtimeWeb", runtimeWeb],
  ["security", security],
  ["skills", skills],
  ["workspace", workspace],
  ["workspaces", workspaces],
]);

messages satisfies typeof enUSMessages;

export default messages;
