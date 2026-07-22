"""Runtime Provider credential verifier tests."""

from cryptography.fernet import Fernet

from .runtime_provider_credential import RuntimeProviderCredentialVerifier


def test_verifier_matches_issued_secret_without_persisting_plaintext() -> None:
    """The verifier accepts its source secret and stores only a digest value."""
    verifier = RuntimeProviderCredentialVerifier(Fernet.generate_key().decode())
    secret = verifier.issue_secret()
    stored_verifier = verifier.verifier_for(secret)

    assert secret
    assert stored_verifier != secret
    assert len(stored_verifier) == 64
    assert verifier.matches(secret, stored_verifier)


def test_verifier_rejects_wrong_secret_and_different_deployment_root() -> None:
    """Verifier comparison is scoped to both plaintext and deployment root."""
    first = RuntimeProviderCredentialVerifier(Fernet.generate_key().decode())
    second = RuntimeProviderCredentialVerifier(Fernet.generate_key().decode())
    secret = first.issue_secret()
    stored_verifier = first.verifier_for(secret)

    assert not first.matches("wrong-secret", stored_verifier)
    assert not second.matches(secret, stored_verifier)
