const { appendFileSync } = require("node:fs");

const runtimeVariableNames = [
  "ACTIONS_RUNTIME_TOKEN",
  "ACTIONS_RUNTIME_URL",
  "ACTIONS_CACHE_URL",
  "ACTIONS_RESULTS_URL",
  "ACTIONS_CACHE_SERVICE_V2",
];
const environmentFile = process.env.GITHUB_ENV;

if (!environmentFile) {
  throw new Error("GITHUB_ENV is required to expose the GitHub Actions runtime.");
}

for (const name of runtimeVariableNames) {
  const value = process.env[name];
  if (!value) {
    continue;
  }

  const delimiter = `azents_${name}_${process.pid}`;
  appendFileSync(
    environmentFile,
    `${name}<<${delimiter}\n${value}\n${delimiter}\n`,
    "utf8",
  );
}
