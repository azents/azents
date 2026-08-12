"""Runtime proxy process and readiness entrypoint."""

import argparse
import http.client
import json
import os
import shutil
import sys
from pathlib import Path

from azents_runtime_proxy.policy import ProxyPolicy, load_proxy_policy

_POLICY_PATH_ENV = "AZ_RUNTIME_PROXY_POLICY_PATH"
_POLICY_DIGEST_ENV = "AZ_RUNTIME_PROXY_POLICY_DIGEST"
_ARTIFACT_DIGEST_ENV = "AZ_RUNTIME_PROXY_ARTIFACT_DIGEST"
_PUBLIC_CA_PATH_ENV = "AZ_RUNTIME_PROXY_PUBLIC_CA_PATH"
_COMBINED_CA_PATH_ENV = "AZ_RUNTIME_PROXY_COMBINED_CA_PATH"
_MITMPROXY_CONFDIR_ENV = "AZ_RUNTIME_PROXY_MITMPROXY_CONFDIR"
_LISTEN_HOST_ENV = "AZ_RUNTIME_PROXY_LISTEN_HOST"
_LISTEN_PORT_ENV = "AZ_RUNTIME_PROXY_LISTEN_PORT"
_READINESS_PORT_ENV = "AZ_RUNTIME_PROXY_READINESS_PORT"
_DEFAULT_LISTEN_HOST = "0.0.0.0"
_DEFAULT_LISTEN_PORT = 8080
_DEFAULT_READINESS_PORT = 8081
_READINESS_RESPONSE_LIMIT = 8_192
_READINESS_KEYS = frozenset(
    {
        "runtime_id",
        "configuration_sequence",
        "policy_digest",
        "ca_fingerprint",
        "artifact_digest",
    }
)


def main() -> None:
    """Validate readiness or replace the process with pinned mitmdump."""
    parser = argparse.ArgumentParser(description="Run the Azents Runtime proxy")
    parser.add_argument("command", choices=("run", "ready"), nargs="?", default="run")
    args = parser.parse_args()
    policy = load_environment_policy()
    if args.command == "ready":
        evidence = running_addon_evidence()
        expected = {
            "runtime_id": policy.runtime_id,
            "configuration_sequence": policy.configuration_sequence,
            "policy_digest": policy.digest,
            "ca_fingerprint": policy.ca_fingerprint,
            "artifact_digest": policy.artifact_digest,
        }
        if evidence != expected:
            raise RuntimeError("running proxy addon evidence mismatch")
        sys.stdout.write(json.dumps({"ready": True, **evidence}) + "\n")
        return
    confdir = prepare_mitmproxy_ca()
    executable = mitmdump_executable()
    os.execv(
        str(executable),
        (
            str(executable),
            *mitmdump_arguments(confdir=confdir),
        ),
    )


def load_environment_policy() -> ProxyPolicy:
    """Load policy and evidence from fixed Provider-owned environment inputs."""
    return load_proxy_policy(
        Path(_required_env(_POLICY_PATH_ENV)),
        expected_policy_digest=_required_env(_POLICY_DIGEST_ENV),
        expected_artifact_digest=_required_env(_ARTIFACT_DIGEST_ENV),
        public_ca_path=Path(_required_env(_PUBLIC_CA_PATH_ENV)),
    )


def prepare_mitmproxy_ca() -> Path:
    """Copy proxy-only CA material into the writable mitmproxy confdir."""
    source = Path(_required_env(_COMBINED_CA_PATH_ENV))
    confdir = Path(_required_env(_MITMPROXY_CONFDIR_ENV))
    confdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = confdir / "mitmproxy-ca.pem"
    temporary = confdir / ".mitmproxy-ca.pem.tmp"
    with source.open("rb") as source_file, temporary.open("wb") as target_file:
        shutil.copyfileobj(source_file, target_file)
        target_file.flush()
        os.fsync(target_file.fileno())
    temporary.chmod(0o600)
    temporary.replace(destination)
    return confdir


def mitmdump_arguments(*, confdir: Path) -> tuple[str, ...]:
    """Return the fixed no-fallback mitmdump launch contract."""
    listen_port = _required_port(
        os.environ.get(_LISTEN_PORT_ENV, str(_DEFAULT_LISTEN_PORT))
    )
    listen_host = os.environ.get(_LISTEN_HOST_ENV, _DEFAULT_LISTEN_HOST)
    if not listen_host:
        raise ValueError("proxy listen host must not be empty")
    addon_script = Path(__file__).with_name("addon_script.py")
    return (
        "--mode",
        "regular",
        "--listen-host",
        listen_host,
        "--listen-port",
        str(listen_port),
        "--set",
        f"confdir={confdir}",
        "--set",
        "connection_strategy=lazy",
        "--set",
        "rawtcp=false",
        "--set",
        "http3=false",
        "--set",
        "ssl_insecure=false",
        "--set",
        "onboarding=false",
        "--set",
        "save_stream_file=",
        "--set",
        "stream_large_bodies=1",
        "--scripts",
        str(addon_script),
        "--quiet",
    )


def mitmdump_executable() -> Path:
    """Return the pinned mitmdump executable installed beside Python."""
    executable = Path(sys.executable).with_name("mitmdump")
    if not executable.is_file():
        raise RuntimeError("pinned mitmdump executable is missing")
    return executable


def readiness_port() -> int:
    """Return the fixed loopback readiness port."""
    return _required_port(
        os.environ.get(_READINESS_PORT_ENV, str(_DEFAULT_READINESS_PORT))
    )


def running_addon_evidence() -> dict[str, str | int]:
    """Read bounded readiness evidence from the running addon instance."""
    connection = http.client.HTTPConnection(
        "127.0.0.1",
        readiness_port(),
        timeout=1.0,
    )
    try:
        connection.request("GET", "/ready")
        response = connection.getresponse()
        body = response.read(_READINESS_RESPONSE_LIMIT + 1)
    finally:
        connection.close()
    if response.status != 200 or len(body) > _READINESS_RESPONSE_LIMIT:
        raise RuntimeError("running proxy addon is not ready")
    try:
        evidence = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("running proxy addon evidence is malformed") from error
    if (
        not isinstance(evidence, dict)
        or set(evidence) != _READINESS_KEYS
        or not isinstance(evidence["runtime_id"], str)
        or isinstance(evidence["configuration_sequence"], bool)
        or not isinstance(evidence["configuration_sequence"], int)
        or not isinstance(evidence["policy_digest"], str)
        or not isinstance(evidence["ca_fingerprint"], str)
        or not isinstance(evidence["artifact_digest"], str)
    ):
        raise RuntimeError("running proxy addon evidence is invalid")
    return {
        "runtime_id": evidence["runtime_id"],
        "configuration_sequence": evidence["configuration_sequence"],
        "policy_digest": evidence["policy_digest"],
        "ca_fingerprint": evidence["ca_fingerprint"],
        "artifact_digest": evidence["artifact_digest"],
    }


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _required_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError("proxy listen port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise ValueError("proxy listen port is invalid")
    return port


if __name__ == "__main__":
    main()
