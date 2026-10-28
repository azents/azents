"""Set offline SDK import conditions before loading provider test prerequisites."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

_PREFIXES = (
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "GOOGLE_",
    "AWS_",
    "AZURE_",
    "XAI_",
    "OPENROUTER_",
    "CHATGPT_",
    "MOONSHOT_",
    "KIMI_",
    "LITELLM_",
    "LANGFUSE_",
    "SENTRY_",
    "OTEL_",
    "HELICONE_",
)
for name in tuple(os.environ):
    if name.startswith(_PREFIXES) or name in {
        "DATABASE_URL",
        "REDIS_URL",
        "WORKER_CONFIG",
        "CONFIG_FILE_PATH",
        "SSLKEYLOGFILE",
    }:
        os.environ.pop(name)
_HOME = TemporaryDirectory(prefix="relay-proxy-tests-")
os.environ["HOME"] = _HOME.name
os.environ["USERPROFILE"] = _HOME.name
os.environ["APPDATA"] = _HOME.name
os.environ["XDG_CONFIG_HOME"] = str(Path(_HOME.name) / ".config")
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

pytest_plugins = ["azents_llm_proxy.pytest_plugin"]
