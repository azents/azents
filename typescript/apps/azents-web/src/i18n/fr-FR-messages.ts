import account from "../../messages/fr-FR/account.json";
import agentWorkspacePicker from "../../messages/fr-FR/agentWorkspacePicker.json";
import appBar from "../../messages/fr-FR/appBar.json";
import auth from "../../messages/fr-FR/auth.json";
import chat from "../../messages/fr-FR/chat.json";
import chatPreview from "../../messages/fr-FR/chatPreview.json";
import common from "../../messages/fr-FR/common.json";
import cta from "../../messages/fr-FR/cta.json";
import elevation from "../../messages/fr-FR/elevation.json";
import externalChannelApproval from "../../messages/fr-FR/externalChannelApproval.json";
import features from "../../messages/fr-FR/features.json";
import footer from "../../messages/fr-FR/footer.json";
import hero from "../../messages/fr-FR/hero.json";
import memberProfile from "../../messages/fr-FR/memberProfile.json";
import metadata from "../../messages/fr-FR/metadata.json";
import nav from "../../messages/fr-FR/nav.json";
import oauth from "../../messages/fr-FR/oauth.json";
import oauthCallback from "../../messages/fr-FR/oauthCallback.json";
import security from "../../messages/fr-FR/security.json";
import skills from "../../messages/fr-FR/skills.json";
import useCases from "../../messages/fr-FR/useCases.json";
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
