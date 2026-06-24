"""runtime-control server CLI entry point."""

import asyncio

from azents.runtime.control_server import run_runtime_control_server


def main() -> None:
    """Run the runtime-control server."""
    asyncio.run(run_runtime_control_server())


if __name__ == "__main__":
    main()
