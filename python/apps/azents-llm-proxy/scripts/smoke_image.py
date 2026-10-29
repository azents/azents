"""Probe the packaged process inside an isolated, nonroot container.

Run with ``docker run --rm --network none -i --entrypoint python IMAGE -`` and
supply this file on stdin. Only credential-free local health/admission is tested;
this is not authority, provider-entitlement or deployment readiness evidence.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def status(path: str) -> int:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:4000" + path, timeout=1
        ) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main() -> None:
    environment = dict(os.environ)
    environment["AZ_LLM_PROXY_AUTHORITY_URL"] = "https://authority.invalid/internal/llm"
    environment["AZ_LLM_PROXY_RESOLVER_KEY"] = (
        "synthetic-image-fixture-resolver-only-32-characters"
    )
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "azents_llm_proxy"],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 45
            while True:
                if process.poll() is not None:
                    log.seek(0)
                    raise AssertionError(
                        "Proxy exited before readiness: " + log.read().decode()
                    )
                try:
                    if status("/health/liveliness") == 200:
                        break
                except OSError:
                    # Retry a not-yet-listening socket until authoritative health
                    # or process exit, bounded by the startup deadline.
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError("Packaged Proxy readiness deadline exceeded.")
                time.sleep(0.1)
            outcomes = {
                "uid": os.getuid(),
                "readiness": status("/health/liveliness"),
                "unauthenticated_models": status("/v1/models"),
                "management": status("/key/generate"),
            }
            assert outcomes == {
                "uid": 65532,
                "readiness": 200,
                "unauthenticated_models": 401,
                "management": 403,
            }
        finally:
            process.terminate()
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(15)
        outcomes["shutdown_exit_code"] = process.returncode
        # Uvicorn restores/re-raises the received signal after its shutdown;
        # reject a timeout-forced SIGKILL, but accept normal SIGTERM completion.
        assert process.returncode in {0, -signal.SIGTERM}
        sys.stdout.write(json.dumps(outcomes, indent=2) + "\n")


if __name__ == "__main__":
    main()
