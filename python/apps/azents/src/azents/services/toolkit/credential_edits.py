"""Typed credential edit decisions with opaque provider-value preservation."""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class _OpaqueCredentialValue:
    """One uninterpreted provider value and its decoded redacted-edit presence."""

    value: object
    blank: bool


@dataclass(frozen=True)
class _CredentialField:
    """One named nested object or opaque leaf in a credential edit."""

    name: str
    value: "CredentialEditObject | _OpaqueCredentialValue"


@dataclass(frozen=True)
class CredentialEditObject:
    """Validated object/discriminator used by credential merge operations.

    Provider-owned leaves are not validated or rewritten here. Only object shape,
    the consumed string discriminator and blank-edit presence are interpreted.
    """

    credential_type: str | None
    fields: tuple[_CredentialField, ...]

    def to_payload(self) -> dict[str, object]:
        """Encode preserved provider values only at the JSON egress boundary."""
        return {
            field.name: (
                field.value.to_payload()
                if isinstance(field.value, CredentialEditObject)
                else field.value.value
            )
            for field in self.fields
        }


@dataclass(frozen=True)
class _ClusterEdit:
    """One configured cluster identity and authentication-method edit."""

    name: str
    auth_type: str


_EMPTY_CREDENTIALS = CredentialEditObject(credential_type=None, fields=())


def decode_credential_values(value: object) -> CredentialEditObject:
    """Decode only the operation-owned object and discriminator at ingress."""
    if not isinstance(value, dict):
        return _EMPTY_CREDENTIALS
    discriminator = value.get("type")
    fields: list[_CredentialField] = []
    for name, raw in value.items():
        if not isinstance(name, str):
            raise ValueError("Credential field names must be strings")
        fields.append(
            _CredentialField(
                name=name,
                value=(
                    decode_credential_values(raw)
                    if isinstance(raw, dict)
                    else _OpaqueCredentialValue(
                        value=raw, blank=raw is None or raw == ""
                    )
                ),
            )
        )
    return CredentialEditObject(
        credential_type=discriminator if isinstance(discriminator, str) else None,
        fields=tuple(fields),
    )


def decode_stored_credential_values(credentials: str | None) -> CredentialEditObject:
    """Retain the existing malformed/non-object stored credential fallback."""
    if credentials is None:
        return _EMPTY_CREDENTIALS
    try:
        decoded: object = json.loads(credentials)
    except json.JSONDecodeError:
        return _EMPTY_CREDENTIALS
    return decode_credential_values(decoded)


def merge_credential_edits(
    existing: CredentialEditObject,
    submitted: CredentialEditObject,
) -> CredentialEditObject:
    """Merge typed redacted edits without inspecting opaque provider leaves."""
    reset = (
        submitted.credential_type is not None
        and submitted.credential_type != existing.credential_type
    )
    fields = {} if reset else {field.name: field.value for field in existing.fields}
    credential_type = None if reset else existing.credential_type
    for field in submitted.fields:
        if field.name == "type":
            if submitted.credential_type is not None:
                fields[field.name] = field.value
                credential_type = submitted.credential_type
            continue
        if isinstance(field.value, CredentialEditObject):
            current = fields.get(field.name)
            nested = merge_credential_edits(
                current
                if isinstance(current, CredentialEditObject)
                else _EMPTY_CREDENTIALS,
                field.value,
            )
            if nested.fields:
                fields[field.name] = nested
        elif not field.value.blank:
            fields[field.name] = field.value
    return CredentialEditObject(
        credential_type=credential_type,
        fields=tuple(
            _CredentialField(name=name, value=value) for name, value in fields.items()
        ),
    )


def merge_redacted_credential_values(
    existing: dict[str, object],
    submitted: dict[str, object],
) -> dict[str, object]:
    """Decode redacted form objects, merge typed edits and encode the result."""
    return merge_credential_edits(
        decode_credential_values(existing), decode_credential_values(submitted)
    ).to_payload()


def _decode_cluster_edits(config: dict[str, object]) -> tuple[_ClusterEdit, ...]:
    """Validate only configured cluster names and authentication discriminators."""
    raw_clusters = config.get("clusters")
    if not isinstance(raw_clusters, list):
        return ()
    clusters: list[_ClusterEdit] = []
    for raw in raw_clusters:
        if not isinstance(raw, dict):
            continue
        name, auth_type = raw.get("name"), raw.get("auth_type")
        if isinstance(name, str) and name and isinstance(auth_type, str):
            clusters.append(_ClusterEdit(name=name, auth_type=auth_type))
    return tuple(clusters)


def _cluster_credentials(
    value: CredentialEditObject,
) -> dict[str, CredentialEditObject]:
    """Select already decoded cluster credential objects for the merge."""
    for field in value.fields:
        if field.name == "clusters" and isinstance(field.value, CredentialEditObject):
            return {
                cluster.name: cluster.value
                for cluster in field.value.fields
                if isinstance(cluster.value, CredentialEditObject)
            }
    return {}


def merge_kubernetes_credentials(
    existing_credentials: str | None,
    submitted_credentials: dict[str, object] | None,
    config: dict[str, object],
) -> dict[str, object]:
    """Merge validated cluster edits while preserving unknown provider values."""
    existing = _cluster_credentials(
        decode_stored_credential_values(existing_credentials)
    )
    submitted = _cluster_credentials(decode_credential_values(submitted_credentials))
    clusters = _decode_cluster_edits(config)
    merged_clusters: dict[str, object] = {}
    for cluster in clusters:
        saved = existing.get(cluster.name, _EMPTY_CREDENTIALS)
        edit = submitted.get(cluster.name, _EMPTY_CREDENTIALS)
        merged = merge_credential_edits(saved, edit)
        if merged.credential_type != cluster.auth_type:
            discriminator = _CredentialField(
                name="type",
                value=_OpaqueCredentialValue(value=cluster.auth_type, blank=False),
            )
            replacement_fields = [
                discriminator if field.name == "type" else field
                for field in edit.fields
            ]
            if not any(field.name == "type" for field in edit.fields):
                replacement_fields.append(discriminator)
            replacement = CredentialEditObject(
                credential_type=cluster.auth_type,
                fields=tuple(replacement_fields),
            )
            merged = merge_credential_edits(_EMPTY_CREDENTIALS, replacement)
        merged_clusters[cluster.name] = merged.to_payload()
    return {"clusters": merged_clusters}
