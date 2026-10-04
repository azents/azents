"""Detached GitHub installation identity at the supported SDK boundary."""

from dataclasses import dataclass

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)


@dataclass(frozen=True)
class GitHubInstallationSnapshot:
    """One validated installation/account identity with original optional avatar."""

    installation_id: int
    app_id: int | None
    account_login: str
    account_type: str
    account_avatar_url: str | None


class _AccountPayload(BaseModel):
    """Known account fields; GitHub's external extension fields remain compatible."""

    model_config = ConfigDict(extra="ignore")

    login: StrictStr
    account_type: StrictStr = Field(alias="type")
    avatar_url: object = None


class _InstallationPayload(BaseModel):
    """Ingress-only provider payload preserving legacy boolean ID acceptance."""

    model_config = ConfigDict(extra="ignore")

    id: StrictInt | StrictBool
    account: _AccountPayload
    app_id: object = None


def decode_github_installations(
    value: object,
) -> tuple[GitHubInstallationSnapshot, ...]:
    """Decode once, preserving order, duplicates, skips and optional avatar values.

    GitHub adds provider fields independently. Unknown fields are ignored under
    that external compatibility contract. A malformed outer list remains empty;
    invalid account/id/name records are skipped as in the original projections.
    """
    if not isinstance(value, list) or not all(
        isinstance(item, dict) and all(isinstance(key, str) for key in item)
        for item in value
    ):
        return ()
    installations: list[GitHubInstallationSnapshot] = []
    for item in value:
        try:
            payload = _InstallationPayload.model_validate(item)
        except ValidationError:
            continue
        installations.append(
            GitHubInstallationSnapshot(
                installation_id=payload.id,
                app_id=payload.app_id if isinstance(payload.app_id, int) else None,
                account_login=payload.account.login,
                account_type=payload.account.account_type,
                account_avatar_url=(
                    payload.account.avatar_url
                    if isinstance(payload.account.avatar_url, str)
                    else None
                ),
            )
        )
    return tuple(installations)
