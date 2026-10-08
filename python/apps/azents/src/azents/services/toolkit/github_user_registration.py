"""Write-only BYOA registration edits without credential reuse across Apps."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from azents.core.github_credentials import GitHubSecrets, GitHubSecretsAppUser

_adapter: TypeAdapter[GitHubSecrets] = TypeAdapter(
    GitHubSecrets, config=ConfigDict(hide_input_in_errors=True)
)


class GitHubUserRegistrationEdit(BaseModel):
    """An edit bag whose omitted secrets retain the same App's saved values."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    type: Literal["github_app_user"]
    app_id: str | None = Field(default=None, min_length=1)
    client_id: str | None = Field(default=None, min_length=1)
    private_key: str | None = Field(default=None, repr=False)
    client_secret: str | None = Field(default=None, repr=False)


def merge_github_user_registration(
    existing_credentials: str | None,
    submitted_credentials: dict[str, object],
) -> dict[str, object]:
    """Merge omitted write-only fields only within the same verified App identity."""
    submitted = GitHubUserRegistrationEdit.model_validate(submitted_credentials)
    if existing_credentials is None:
        return submitted.model_dump(exclude_unset=True)
    existing = _adapter.validate_json(existing_credentials)
    if not isinstance(existing, GitHubSecretsAppUser):
        return submitted.model_dump(exclude_unset=True)
    if "app_id" in submitted.model_fields_set and submitted.app_id != existing.app_id:
        return submitted.model_dump(exclude_unset=True)
    retained = existing.model_dump()
    if (
        "client_id" in submitted.model_fields_set
        and submitted.client_id != existing.client_id
    ):
        retained.pop("client_secret")
    return {**retained, **submitted.model_dump(exclude_unset=True)}
