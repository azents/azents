"""Execing Linux PTY launcher for interactive Runtime Terminals."""

import argparse
import fcntl
import os
import struct
import termios
from pathlib import Path

_BASH_PATH = "/bin/bash"


def main() -> None:
    """Create a Terminal session and replace the launcher with Bash."""
    parser = argparse.ArgumentParser(description="Launch an Azents Runtime Terminal")
    parser.add_argument("--slave-fd", type=int, required=True)
    parser.add_argument("--working-directory", required=True)
    arguments = parser.parse_args()
    configure_linux_pty_child(arguments.slave_fd)
    os.chdir(Path(arguments.working_directory))
    os.execv(_BASH_PATH, (_BASH_PATH, "--login"))


def configure_linux_pty_child(slave_fd: int) -> None:
    """Create the Terminal controlling session and attach standard streams.

    :param slave_fd: Open PTY slave file descriptor inherited by the launcher.
    """
    os.setsid()
    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
    os.dup2(slave_fd, 0)
    os.dup2(slave_fd, 1)
    os.dup2(slave_fd, 2)
    if slave_fd > 2:
        os.close(slave_fd)


def set_pty_size(*, fd: int, columns: int, rows: int) -> None:
    """Set a PTY's visible terminal dimensions.

    :param fd: Open PTY file descriptor.
    :param columns: Requested positive terminal column count.
    :param rows: Requested positive terminal row count.
    """
    if columns <= 0 or rows <= 0:
        raise ValueError("Terminal dimensions must be positive.")
    fcntl.ioctl(
        fd,
        termios.TIOCSWINSZ,
        struct.pack("HHHH", rows, columns, 0, 0),
    )


if __name__ == "__main__":
    main()
