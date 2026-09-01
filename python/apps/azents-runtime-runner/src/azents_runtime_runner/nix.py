"""Configure Nix to use the persistent Runtime home directory."""

import os
from collections.abc import Mapping
from pathlib import Path

_NIX_CONFIG = """\
experimental-features = nix-command flakes
sandbox = false
"""


def prepare_nix_environment(
    *,
    workspace_path: str,
) -> Mapping[str, str]:
    """Place Nix store and state under the existing persistent Runtime home."""
    home = Path(workspace_path)
    nix_root = home / ".nix"
    config_dir = nix_root / "etc/nix"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "nix.conf"
    if not config_path.exists():
        config_path.write_text(_NIX_CONFIG)
    profile = home / ".local/state/nix/profiles/profile"
    path = os.environ.get("PATH", "")
    return {
        "NIX_STORE_DIR": str(nix_root / "store"),
        "NIX_STATE_DIR": str(nix_root / "var/nix"),
        "NIX_LOG_DIR": str(nix_root / "var/log/nix"),
        "NIX_CONF_DIR": str(config_dir),
        "NIX_PROFILE": str(profile),
        "NIX_SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
        "PATH": os.pathsep.join(
            dict.fromkeys(
                (
                    str(profile / "bin"),
                    *(part for part in path.split(os.pathsep) if part),
                )
            )
        ),
    }
