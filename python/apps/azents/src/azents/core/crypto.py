"""Credential encryption/decryption utilities.

Protects LLM provider credentials using Fernet symmetric encryption.
"""

from cryptography.fernet import Fernet


class CredentialCipher:
    """Fernet-based credential encryption/decryption."""

    def __init__(self, key: str) -> None:
        """
        :param key: Fernet encryption key, base64-encoded 32-byte key
        """
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext.

        :param plaintext: Plaintext to encrypt
        :return: Encrypted string
        """
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext.

        :param ciphertext: Ciphertext to decrypt
        :return: Decrypted plaintext
        """
        return self._fernet.decrypt(ciphertext.encode()).decode()
