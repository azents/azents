import account from "../../messages/ko-KR/account.json";
import agentWorkspacePicker from "../../messages/ko-KR/agentWorkspacePicker.json";
import appBar from "../../messages/ko-KR/appBar.json";
import auth from "../../messages/ko-KR/auth.json";
import chat from "../../messages/ko-KR/chat.json";
import common from "../../messages/ko-KR/common.json";
import elevation from "../../messages/ko-KR/elevation.json";
import externalAccountLinks from "../../messages/ko-KR/externalAccountLinks.json";
import externalChannelApproval from "../../messages/ko-KR/externalChannelApproval.json";
import githubAppGuide from "../../messages/ko-KR/githubAppGuide.json";
import googleToolkit from "../../messages/ko-KR/googleToolkit.json";
import memberProfile from "../../messages/ko-KR/memberProfile.json";
import metadata from "../../messages/ko-KR/metadata.json";
import oauth from "../../messages/ko-KR/oauth.json";
import oauthCallback from "../../messages/ko-KR/oauthCallback.json";
import runtimeLifecycle from "../../messages/ko-KR/runtimeLifecycle.json";
import runtimeMetrics from "../../messages/ko-KR/runtimeMetrics.json";
import runtimeWeb from "../../messages/ko-KR/runtimeWeb.json";
import security from "../../messages/ko-KR/security.json";
import skills from "../../messages/ko-KR/skills.json";
import toolkitSetup from "../../messages/ko-KR/toolkitSetup.json";
import workspace from "../../messages/ko-KR/workspace.json";
import workspaces from "../../messages/ko-KR/workspaces.json";
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
  ["githubAppGuide", githubAppGuide],
  ["googleToolkit", googleToolkit],
  ["memberProfile", memberProfile],
  ["metadata", metadata],
  ["oauth", oauth],
  ["oauthCallback", oauthCallback],
  ["runtimeLifecycle", runtimeLifecycle],
  ["runtimeMetrics", runtimeMetrics],
  ["runtimeWeb", runtimeWeb],
  ["security", security],
  ["skills", skills],
  ["toolkitSetup", toolkitSetup],
  ["workspace", workspace],
  ["workspaces", workspaces],
]);

messages satisfies typeof enUSMessages;

export default messages;
