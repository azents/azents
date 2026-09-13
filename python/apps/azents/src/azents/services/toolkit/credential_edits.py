"""Credential merging for redacted Toolkit edit forms."""

import json


def merge_redacted_credential_values(
    existing: dict[str, object],
    submitted: dict[str, object],
) -> dict[str, object]:
    """Merge non-empty submitted values into credentials hidden from the editor.

    A changed discriminator starts a new credential object so secrets from a
    different authentication method cannot carry across the change.

    :param existing: Stored credential object
    :param submitted: Redacted form credential object
    :return: Merged credential object
    """
    submitted_type = submitted.get("type")
    existing_type = existing.get("type")
    merged = (
        {}
        if isinstance(submitted_type, str) and submitted_type != existing_type
        else dict(existing)
    )

    for key, value in submitted.items():
        if key == "type":
            if isinstance(value, str):
                merged[key] = value
            continue
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            current = merged.get(key)
            nested = merge_redacted_credential_values(
                current if isinstance(current, dict) else {},
                value,
            )
            if nested:
                merged[key] = nested
            continue
        merged[key] = value

    return merged


def merge_kubernetes_credentials(
    existing_credentials: str | None,
    submitted_credentials: dict[str, object] | None,
    config: dict[str, object],
) -> dict[str, object]:
    """Merge Kubernetes cluster credentials against the edited cluster config.

    :param existing_credentials: Stored encrypted credential plaintext
    :param submitted_credentials: Redacted form credential edits
    :param config: Edited Kubernetes Toolkit config
    :return: Credentials for currently configured clusters
    """
    existing = _decode_credentials(existing_credentials)
    existing_clusters = _object_value(existing, "clusters")
    submitted_clusters = _object_value(submitted_credentials, "clusters")
    merged_clusters: dict[str, object] = {}

    raw_clusters = config.get("clusters")
    if not isinstance(raw_clusters, list):
        return {"clusters": merged_clusters}

    for raw_cluster in raw_clusters:
        if not isinstance(raw_cluster, dict):
            continue
        name = raw_cluster.get("name")
        auth_type = raw_cluster.get("auth_type")
        if not isinstance(name, str) or not name or not isinstance(auth_type, str):
            continue

        saved = existing_clusters.get(name)
        submitted = submitted_clusters.get(name)
        saved_object = saved if isinstance(saved, dict) else {}
        submitted_object = submitted if isinstance(submitted, dict) else {}
        merged = merge_redacted_credential_values(saved_object, submitted_object)
        if merged.get("type") != auth_type:
            merged = merge_redacted_credential_values(
                {},
                {**submitted_object, "type": auth_type},
            )
        merged_clusters[name] = merged

    return {"clusters": merged_clusters}


def _decode_credentials(credentials: str | None) -> dict[str, object]:
    """Decode one stored credential object without exposing malformed values."""
    if credentials is None:
        return {}
    try:
        decoded: object = json.loads(credentials)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _object_value(
    value: dict[str, object] | None,
    key: str,
) -> dict[str, object]:
    """Return one nested object value or an empty mapping."""
    if value is None:
        return {}
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}
