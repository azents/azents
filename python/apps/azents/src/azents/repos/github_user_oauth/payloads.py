"""Typed encrypted payload boundaries for user OAuth persistence."""

import dataclasses

from pydantic import BaseModel, ConfigDict, Field

from azents.core.crypto import CredentialCipher
from azents.core.github_user_oauth import (
    GitHubUserAttempt,
    GitHubUserCandidate,
    GitHubUserCleanup,
    GitHubUserConnection,
    GitHubUserRegistration,
    GitHubUserRequester,
)
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserCleanup,
    RDBGitHubUserConnection,
)


class SetupPayload(BaseModel):
    """Only the encrypted setup envelope contains verifier and client secret."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    registration: GitHubUserRegistration
    redirect_uri: str
    nonce: str = Field(repr=False)
    code_verifier: str = Field(repr=False)


class CleanupPayload(BaseModel):
    """Retired access token and original cleanup authentication."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    registration: GitHubUserRegistration
    access_token: str = Field(repr=False)


class CandidatePayload(BaseModel):
    """Verified candidate account without provider envelope fields."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    candidate: GitHubUserCandidate


class RegistrationPayload(BaseModel):
    """Active App binding without a copied platform client secret."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    registration: GitHubUserRegistration


def encode_registration(
    registration: GitHubUserRegistration, cipher: CredentialCipher
) -> str:
    """Encode the nonsecret active binding into the credential envelope."""
    return cipher.encrypt(
        RegistrationPayload(
            registration=dataclasses.replace(registration, client_secret=None)
        ).model_dump_json()
    )


def connection_from(
    row: RDBGitHubUserConnection, cipher: CredentialCipher
) -> GitHubUserConnection:
    """Decode only after an authorized repository read."""
    registration = RegistrationPayload.model_validate_json(
        cipher.decrypt(row.encrypted_registration)
    ).registration
    return GitHubUserConnection(
        id=row.id,
        toolkit_id=row.toolkit_id,
        registration=registration,
        access_token=cipher.decrypt(row.encrypted_access_token),
        account_id=row.account_id,
        account_login=row.account_login,
        account_avatar_url=row.account_avatar_url,
        status=row.status,
        failure_reason=row.failure_reason,
    )


def attempt_from(
    row: RDBGitHubUserAttempt, cipher: CredentialCipher
) -> GitHubUserAttempt:
    """Decode setup and candidate as detached domain facts."""
    setup = SetupPayload.model_validate_json(cipher.decrypt(row.encrypted_setup))
    candidate = (
        None
        if row.encrypted_candidate is None
        else CandidatePayload.model_validate_json(
            cipher.decrypt(row.encrypted_candidate)
        ).candidate
    )
    return GitHubUserAttempt(
        id=row.id,
        requester=GitHubUserRequester(
            user_id=row.user_id,
            session_id=row.session_id,
            workspace_id=row.workspace_id,
            agent_id=row.agent_id,
            toolkit_id=row.toolkit_id,
        ),
        registration=setup.registration,
        redirect_uri=setup.redirect_uri,
        nonce=setup.nonce,
        code_verifier=setup.code_verifier,
        expires_at=row.expires_at,
        captured_connection_id=row.captured_connection_id,
        status=row.status,
        candidate=candidate,
    )


def cleanup_from(
    row: RDBGitHubUserCleanup, cipher: CredentialCipher
) -> GitHubUserCleanup:
    """Decode retirement data only for provider cleanup."""
    payload = CleanupPayload.model_validate_json(cipher.decrypt(row.encrypted_payload))
    return GitHubUserCleanup(
        id=row.id,
        toolkit_id=row.toolkit_id,
        registration=payload.registration,
        access_token=payload.access_token,
        reason=row.reason,
        status=row.status,
        failure_reason=row.failure_reason,
    )
