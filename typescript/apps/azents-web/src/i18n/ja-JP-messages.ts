import account from "../../messages/ja-JP/account.json";
import agentWorkspacePicker from "../../messages/ja-JP/agentWorkspacePicker.json";
import appBar from "../../messages/ja-JP/appBar.json";
import auth from "../../messages/ja-JP/auth.json";
import chat from "../../messages/ja-JP/chat.json";
import chatPreview from "../../messages/ja-JP/chatPreview.json";
import common from "../../messages/ja-JP/common.json";
import cta from "../../messages/ja-JP/cta.json";
import elevation from "../../messages/ja-JP/elevation.json";
import externalChannelApproval from "../../messages/ja-JP/externalChannelApproval.json";
import features from "../../messages/ja-JP/features.json";
import footer from "../../messages/ja-JP/footer.json";
import hero from "../../messages/ja-JP/hero.json";
import memberProfile from "../../messages/ja-JP/memberProfile.json";
import metadata from "../../messages/ja-JP/metadata.json";
import nav from "../../messages/ja-JP/nav.json";
import oauth from "../../messages/ja-JP/oauth.json";
import oauthCallback from "../../messages/ja-JP/oauthCallback.json";
import runtimeLifecycle from "../../messages/ja-JP/runtimeLifecycle.json";
import runtimeMetrics from "../../messages/ja-JP/runtimeMetrics.json";
import security from "../../messages/ja-JP/security.json";
import skills from "../../messages/ja-JP/skills.json";
import useCases from "../../messages/ja-JP/useCases.json";
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
  ["chatPreview", chatPreview],
  ["common", common],
  ["cta", cta],
  ["elevation", elevation],
  ["externalChannelApproval", externalChannelApproval],
  ["features", features],
  ["footer", footer],
  ["hero", hero],
  ["memberProfile", memberProfile],
  ["metadata", metadata],
  ["nav", nav],
  ["oauth", oauth],
  ["oauthCallback", oauthCallback],
  ["runtimeLifecycle", runtimeLifecycle],
  ["runtimeMetrics", runtimeMetrics],
  ["security", security],
  ["skills", skills],
  ["useCases", useCases],
  ["workspace", workspace],
  ["workspaces", workspaces],
]);

messages satisfies typeof enUSMessages;

export default messages;
