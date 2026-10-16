# /// script
# requires-python = ">=3.14"
# dependencies = ["PyNaCl==1.6.2"]
# ///
"""Encrypt one delegated environment value for confidential Browser fill."""

import argparse
import base64
import binascii
import os
import re
import sys
from collections.abc import Mapping

from nacl.exceptions import CryptoError
from nacl.public import PublicKey, SealedBox


def encrypt_environment(name: str, environment: Mapping[str, str]) -> str:
    """Read a named value internally and return only canonical ciphertext."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        raise ValueError("Invalid environment variable name")
    public = environment.get("AZENTS_BROWSER_INPUT_PUBLIC_KEY")
    if public is None:
        raise ValueError("Browser input public key is unavailable")
    if name not in environment:
        raise ValueError("Source environment variable is unavailable")
    try:
        key = base64.b64decode(public, altchars=b"-_", validate=True)
        if len(key) != 32 or base64.urlsafe_b64encode(key).decode("ascii") != public:
            raise ValueError
    except ValueError, binascii.Error:
        raise ValueError("Browser input public key is invalid") from None
    try:
        value = environment[name].encode("utf-8")
    except UnicodeError:
        raise ValueError("Source environment value is not valid UTF-8") from None
    if len(value) > 4096:
        raise ValueError("Source environment value exceeds the input limit")
    try:
        ciphertext = SealedBox(PublicKey(key)).encrypt(value)
    except CryptoError:
        raise ValueError("Browser input encryption failed") from None
    return base64.urlsafe_b64encode(ciphertext).decode("ascii")


def main() -> int:
    """Provide a name-only CLI with bounded stdout and fixed failure reasons."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, help="Source environment variable name")
    arguments = parser.parse_args()
    try:
        result = encrypt_environment(arguments.env, os.environ)
    except ValueError as error:
        sys.stderr.write(str(error) + "\n")
        return 1
    try:
        sys.stdout.write(result + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Prevent interpreter shutdown from printing a second broken-pipe traceback.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
