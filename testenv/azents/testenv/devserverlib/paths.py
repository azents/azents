"""Internal paths for testenv/azents.

Resolve paths from `Path.resolve()` so tmux and subprocess calls can use
absolute paths without depending on the caller's current working directory.
"""

from pathlib import Path

# testenv/azents/ — three levels above this file (paths.py).
THIS_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = THIS_DIR.parent.parent
AZENTS_DIR = REPO_ROOT / "python" / "apps" / "azents"
COMPOSE_FILE = THIS_DIR / "docker-compose.yaml"
ALEMBIC_INI = AZENTS_DIR / "db-schemas" / "rdb" / "alembic.ini"
ALEMBIC_REVISION_FILE = AZENTS_DIR / "db-schemas" / "rdb" / "revision"
STATE_DIR = THIS_DIR / ".state"
STATE_FILE = STATE_DIR / "devserver.state.json"
LOG_FILE = STATE_DIR / "devserver.log"
SYSTEM_DOCKER_PROVIDER_LOG_FILE = STATE_DIR / "system-docker-provider.log"
ENV_FILE = THIS_DIR / ".env"

SESSION_NAME = "azents-testenv-devserver"
SYSTEM_DOCKER_PROVIDER_SESSION_NAME = "azents-testenv-system-docker-provider"
COMPOSE_PROJECT = "azents-testenv"

# Stage 4 — azents-web (Next.js) tmux session and logs.
TYPESCRIPT_DIR = REPO_ROOT / "typescript"
AZENTS_WEB_DIR = TYPESCRIPT_DIR / "apps" / "azents-web"
WEB_SESSION_NAME = "azents-testenv-web"
WEB_LOG_FILE = STATE_DIR / "web.log"

# Stage 4 default port.
DEFAULT_WEB_PORT = 3003

# Exit codes returned by the CLI.
EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_NOT_RUNNING = 2
EXIT_ERROR = 3
