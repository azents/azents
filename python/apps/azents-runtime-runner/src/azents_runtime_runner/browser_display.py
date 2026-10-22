"""Own a headed browser display only where the host has no native display."""

import asyncio
import contextlib
import os
import sys


class BrowserDisplayError(RuntimeError):
    """The headed browser display could not be established."""


class BrowserDisplay:
    """Keep a Linux virtual display private to this browser manager's children."""

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.environment: dict[str, str | float] | None = None

    async def start(self) -> dict[str, str | float] | None:
        """Reuse native display selection or wait for Xvfb's readiness record."""
        if sys.platform != "linux" or os.environ.get("DISPLAY"):
            return None
        if self.process is not None:
            if self.process.returncode is not None:
                raise BrowserDisplayError("Browser display stopped")
            return self.environment
        try:
            self.process = await asyncio.create_subprocess_exec(
                "Xvfb",
                "-displayfd",
                "1",
                "-screen",
                "0",
                "1280x900x24",
                "-nolisten",
                "tcp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            raise BrowserDisplayError(
                "Browser display executable is unavailable"
            ) from None
        try:
            assert self.process.stdout is not None
            record = await asyncio.wait_for(self.process.stdout.readline(), timeout=5)
            number = record.strip()
            if not number.isdigit() or len(number) > 5:
                raise BrowserDisplayError("Browser display readiness is invalid")
            self.environment = {**os.environ, "DISPLAY": f":{int(number)}"}
            return self.environment
        except TimeoutError:
            await self.close()
            raise BrowserDisplayError("Browser display startup timed out") from None
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """Terminate and reap only the display process created by this owner."""
        process, self.process = self.process, None
        self.environment = None
        if process is None:
            return
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        else:
            await process.wait()
