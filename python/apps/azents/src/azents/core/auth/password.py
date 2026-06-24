"""Password hashing and verification.

Provides password hashing and verification using bcrypt.
"""

import re

import bcrypt

# Password policy constants
MIN_PASSWORD_LENGTH = 8


class WeakPasswordError(Exception):
    """Password does not satisfy policy."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_password_strength(password: str) -> None:
    """Validate password strength.

    Policy:
    - At least 8 characters
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one digit
    - Contains at least one special character

    :param password: Password to validate
    :raises WeakPasswordError: When password does not satisfy policy
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )

    if not re.search(r"[a-z]", password):
        raise WeakPasswordError("Password must contain at least one lowercase letter")

    if not re.search(r"[A-Z]", password):
        raise WeakPasswordError("Password must contain at least one uppercase letter")

    if not re.search(r"\d", password):
        raise WeakPasswordError("Password must contain at least one digit")

    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        raise WeakPasswordError("Password must contain at least one special character")


def hash_password(password: str) -> str:
    """Hash password with bcrypt.

    :param password: Plaintext password
    :return: Hashed password in bcrypt format
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password.

    :param password: Plaintext password to verify
    :param hashed_password: Stored hashed password
    :return: True when password matches
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError, TypeError:
        # Invalid hash format or similar cases
        return False
