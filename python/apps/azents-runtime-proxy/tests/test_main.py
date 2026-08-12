"""Proxy process launch and private-CA preparation tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from azents_runtime_proxy.main import (
    mitmdump_arguments,
    mitmdump_executable,
    prepare_mitmproxy_ca,
    running_addon_evidence,
)


def test_mitmdump_arguments_disable_fallback_and_unsafe_protocols(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("AZ_RUNTIME_PROXY_LISTEN_HOST", raising=False)
    monkeypatch.delenv("AZ_RUNTIME_PROXY_LISTEN_PORT", raising=False)

    arguments = mitmdump_arguments(confdir=tmp_path)

    joined = " ".join(arguments)
    assert "--mode regular" in joined
    assert "connection_strategy=lazy" in arguments
    assert "rawtcp=false" in arguments
    assert "http3=false" in arguments
    assert "ssl_insecure=false" in arguments
    assert "onboarding=false" in arguments
    assert "save_stream_file=" in arguments
    assert "stream_large_bodies=1" in arguments
    assert "transparent" not in joined
    assert "upstream" not in joined
    assert "ignore_hosts" not in joined


def test_prepare_mitmproxy_ca_copies_private_material_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "mounted" / "mitmproxy-ca.pem"
    source.parent.mkdir()
    source.write_bytes(b"private-and-public")
    confdir = tmp_path / "runtime" / "mitmproxy"
    monkeypatch.setenv("AZ_RUNTIME_PROXY_COMBINED_CA_PATH", str(source))
    monkeypatch.setenv("AZ_RUNTIME_PROXY_MITMPROXY_CONFDIR", str(confdir))

    result = prepare_mitmproxy_ca()

    destination = result / "mitmproxy-ca.pem"
    assert destination.read_bytes() == b"private-and-public"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not (confdir / ".mitmproxy-ca.pem.tmp").exists()
    assert os.access(destination, os.R_OK)


def test_mitmdump_executable_is_the_pinned_virtualenv_binary() -> None:
    executable = mitmdump_executable()

    assert executable.name == "mitmdump"
    assert executable.is_file()


def test_module_execution_invokes_main_and_rejects_missing_policy() -> None:
    result = subprocess.run(
        (sys.executable, "-m", "azents_runtime_proxy.main", "ready"),
        check=False,
        capture_output=True,
        text=True,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AZ_RUNTIME_PROXY_")
        },
    )

    assert result.returncode != 0
    assert "AZ_RUNTIME_PROXY_POLICY_PATH" in result.stderr


def test_running_addon_evidence_rejects_unavailable_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZ_RUNTIME_PROXY_READINESS_PORT", "1")

    with pytest.raises(ConnectionError):
        running_addon_evidence()
