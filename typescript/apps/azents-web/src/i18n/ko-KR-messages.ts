import account from "../../messages/ko-KR/account.json";
import agentWorkspacePicker from "../../messages/ko-KR/agentWorkspacePicker.json";
import appBar from "../../messages/ko-KR/appBar.json";
import auth from "../../messages/ko-KR/auth.json";
import chat from "../../messages/ko-KR/chat.json";
import chatPreview from "../../messages/ko-KR/chatPreview.json";
import common from "../../messages/ko-KR/common.json";
import cta from "../../messages/ko-KR/cta.json";
import elevation from "../../messages/ko-KR/elevation.json";
import externalChannelApproval from "../../messages/ko-KR/externalChannelApproval.json";
import features from "../../messages/ko-KR/features.json";
import footer from "../../messages/ko-KR/footer.json";
import hero from "../../messages/ko-KR/hero.json";
import memberProfile from "../../messages/ko-KR/memberProfile.json";
import metadata from "../../messages/ko-KR/metadata.json";
import nav from "../../messages/ko-KR/nav.json";
import oauth from "../../messages/ko-KR/oauth.json";
import oauthCallback from "../../messages/ko-KR/oauthCallback.json";
import security from "../../messages/ko-KR/security.json";
import skills from "../../messages/ko-KR/skills.json";
import useCases from "../../messages/ko-KR/useCases.json";
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
  ["security", security],
  ["skills", skills],
  ["useCases", useCases],
  ["workspace", workspace],
  ["workspaces", workspaces],
]);

messages satisfies typeof enUSMessages;

export default messages;
