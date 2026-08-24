import account from "../../messages/en-US/account.json";
import agentWorkspacePicker from "../../messages/en-US/agentWorkspacePicker.json";
import appBar from "../../messages/en-US/appBar.json";
import auth from "../../messages/en-US/auth.json";
import chat from "../../messages/en-US/chat.json";
import chatPreview from "../../messages/en-US/chatPreview.json";
import common from "../../messages/en-US/common.json";
import cta from "../../messages/en-US/cta.json";
import elevation from "../../messages/en-US/elevation.json";
import externalChannelApproval from "../../messages/en-US/externalChannelApproval.json";
import features from "../../messages/en-US/features.json";
import footer from "../../messages/en-US/footer.json";
import hero from "../../messages/en-US/hero.json";
import memberProfile from "../../messages/en-US/memberProfile.json";
import metadata from "../../messages/en-US/metadata.json";
import nav from "../../messages/en-US/nav.json";
import oauth from "../../messages/en-US/oauth.json";
import oauthCallback from "../../messages/en-US/oauthCallback.json";
import runtimeMetrics from "../../messages/en-US/runtimeMetrics.json";
import security from "../../messages/en-US/security.json";
import skills from "../../messages/en-US/skills.json";
import useCases from "../../messages/en-US/useCases.json";
import workspace from "../../messages/en-US/workspace.json";
import workspaces from "../../messages/en-US/workspaces.json";
import { composeMessages } from "./message-composition";

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
  ["runtimeMetrics", runtimeMetrics],
  ["security", security],
  ["skills", skills],
  ["useCases", useCases],
  ["workspace", workspace],
  ["workspaces", workspaces],
]);

export default messages;
