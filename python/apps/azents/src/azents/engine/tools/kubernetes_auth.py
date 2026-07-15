"""Kubernetes authentication module.

Supports kubeconfig, token, EKS, and GKE authentication.
Creates async ApiClient based on kubernetes_asyncio.
"""

import asyncio
import base64
import json
import logging
import tempfile
import urllib.request
from collections.abc import Mapping
from typing import Annotated, Any, Literal, NamedTuple

import boto3
import google.auth.transport.requests
import yaml
from botocore.signers import RequestSigner
from google.oauth2 import service_account
from kubernetes_asyncio.client import ApiClient, Configuration
from kubernetes_asyncio.config import new_client_from_config_dict
from lightkube import AsyncClient
from lightkube.config.kubeconfig import KubeConfig
from lightkube.config.models import Cluster as LightkubeCluster
from lightkube.config.models import User as LightkubeUser
from pydantic import BaseModel, Field

from azents.core.tools import ClusterConfig

logger = logging.getLogger(__name__)


class GkeClusterInfo(NamedTuple):
    """GKE API endpoint and base64-encoded cluster CA certificate."""

    endpoint: str
    ca_cert_b64: str


# ---------------------------------------------------------------------------
# Credential models
# ---------------------------------------------------------------------------


class KubeconfigCredential(BaseModel):
    """kubeconfig YAML based authentication."""

    type: Literal["kubeconfig"] = "kubeconfig"
    kubeconfig_yaml: str = Field(description="raw kubeconfig YAML string")


class TokenCredential(BaseModel):
    """Service Account token based authentication."""

    type: Literal["token"] = "token"
    token: str = Field(description="Service Account token")
    ca_cert: str | None = Field(
        default=None,
        description="base64-encoded CA certificate",
    )


class EksCredential(BaseModel):
    """AWS EKS IAM based authentication."""

    type: Literal["eks"] = "eks"
    aws_access_key_id: str = Field(description="AWS Access Key ID")
    aws_secret_access_key: str = Field(description="AWS Secret Access Key")
    role_arn: str | None = Field(
        default=None,
        description="IAM Role ARN to assume",
    )


class GkeCredential(BaseModel):
    """Google GKE Service Account based authentication."""

    type: Literal["gke"] = "gke"
    service_account_key: dict[str, object] = Field(
        description="GCP Service Account key JSON",
    )


ClusterCredential = Annotated[
    KubeconfigCredential | TokenCredential | EksCredential | GkeCredential,
    Field(discriminator="type"),
]
"""Per-cluster credential (discriminated union)."""


class KubernetesCredentials(BaseModel):
    """Container for all cluster credentials."""

    clusters: dict[
        str,
        KubeconfigCredential | TokenCredential | EksCredential | GkeCredential,
    ] = Field(
        description="Cluster name to credential mapping",
    )


def parse_credentials(credentials_json: str | None) -> KubernetesCredentials:
    """Parse KubernetesCredentials from JSON string.

    :param credentials_json: Decrypted credential JSON
    :return: Parsed KubernetesCredentials
    :raises ValueError: When credential is absent or malformed
    """
    if credentials_json is None:
        msg = "Kubernetes toolkit requires credentials"
        raise ValueError(msg)
    return KubernetesCredentials.model_validate_json(credentials_json)


# ---------------------------------------------------------------------------
# kubeconfig validation
# ---------------------------------------------------------------------------


def validate_kubeconfig(kubeconfig_dict: Mapping[str, object]) -> None:
    """Reject exec provider in kubeconfig.

    exec provider can run arbitrary commands, so it has RCE risk. Allow only static
    authentication methods such as token and client-certificate-data.

    :param kubeconfig_dict: Parsed kubeconfig dict
    :raises ValueError: When exec provider is found
    """
    users = kubeconfig_dict.get("users")
    if not isinstance(users, list):
        return
    for user_entry in users:
        if not isinstance(user_entry, dict):
            continue
        user = user_entry.get("user")
        if not isinstance(user, dict):
            continue
        if "exec" in user:
            msg = (
                "Kubeconfig with exec provider is not allowed "
                "for security reasons (RCE risk). "
                "Use token or client-certificate-data instead."
            )
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# CA cert helpers
# ---------------------------------------------------------------------------


def _write_ca_cert(ca_cert_b64: str) -> str:
    """Write base64-encoded CA cert to temporary file and return path.

    :param ca_cert_b64: base64-encoded CA certificate data
    :return: Temporary file path
    """
    ca_data = base64.b64decode(ca_cert_b64)
    # Keep file with delete=False; ApiClient must read it during SSL handshake
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        delete=False,
        suffix=".crt",
    )
    tmp.write(ca_data)
    tmp.flush()
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# EKS authentication
# ---------------------------------------------------------------------------


def _assume_role_sync(
    session: boto3.Session,
    role_arn: str,
) -> dict[str, Any]:
    """Call STS assume_role synchronously. Used from asyncio.to_thread.

    :param session: boto3 Session
    :param role_arn: IAM Role ARN to assume
    :return: assume_role response dict
    """
    sts = session.client("sts")
    return sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="azents-k8s-toolkit",
    )


def _describe_eks_cluster_sync(
    session: boto3.Session,
    cluster_name: str,
    region: str,
) -> dict[str, Any]:
    """Call EKS describe_cluster synchronously. Used from asyncio.to_thread.

    :param session: boto3 Session
    :param cluster_name: EKS cluster name
    :param region: AWS region
    :return: describe_cluster response dict
    """
    eks_client = session.client("eks", region_name=region)
    return eks_client.describe_cluster(name=cluster_name)


def _generate_eks_token(
    session: boto3.Session,
    cluster_name: str,
    region: str,
) -> str:
    """Create STS presigned URL based token for EKS cluster.

    :param session: boto3 Session
    :param cluster_name: EKS cluster name
    :param region: AWS region
    :return: Token in k8s-aws-v1.{encoded} format
    """
    sts = session.client("sts", region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        msg = "Failed to retrieve AWS credentials from session"
        raise ValueError(msg)
    signer = RequestSigner(
        sts.meta.service_model.service_id,
        region,
        "sts",
        "v4",
        credentials,
        session.events,
    )
    url = (
        f"https://sts.{region}.amazonaws.com/"
        "?Action=GetCallerIdentity&Version=2011-06-15"
    )
    signed = signer.generate_presigned_url(
        {
            "method": "GET",
            "url": url,
            "body": {},
            "headers": {"x-k8s-aws-id": cluster_name},
            "context": {},
        },
        region_name=region,
        expires_in=60,
        operation_name="",
    )
    encoded = base64.urlsafe_b64encode(signed.encode()).decode().rstrip("=")
    return f"k8s-aws-v1.{encoded}"


async def _create_eks_client(
    cluster: ClusterConfig,
    credential: EksCredential,
    proxy_url: str | None,
) -> ApiClient:
    """Create ApiClient for EKS cluster.

    1. Create boto3 session (optional assume_role)
    2. Fetch endpoint + CA cert with eks.describe_cluster
    3. Create STS presigned URL token
    4. Configure automatic refresh with refresh_api_key_hook
    5. Configure SSRF prevention proxy

    Wrap synchronous boto3 calls with to_thread to avoid blocking event loop.

    :param cluster: Cluster settings
    :param credential: EKS credential
    :param proxy_url: egress proxy URL
    :return: Configured ApiClient
    :raises ValueError: When cluster_name or region is absent
    """
    if not cluster.cluster_name:
        msg = "cluster_name is required for EKS authentication"
        raise ValueError(msg)
    if not cluster.region:
        msg = "region is required for EKS authentication"
        raise ValueError(msg)

    # Create boto3 session; simple non-CPU-bound object creation, so sync is OK
    session = boto3.Session(
        aws_access_key_id=credential.aws_access_key_id,
        aws_secret_access_key=credential.aws_secret_access_key,
        region_name=cluster.region,
    )

    # assume role (optional); STS API call is synchronous, so use to_thread
    if credential.role_arn:
        assumed = await asyncio.to_thread(
            _assume_role_sync,
            session,
            credential.role_arn,
        )
        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=cluster.region,
        )

    # Fetch endpoint + CA cert with describe_cluster; EKS API call is synchronous
    cluster_info = await asyncio.to_thread(
        _describe_eks_cluster_sync,
        session,
        cluster.cluster_name,
        cluster.region,
    )
    endpoint: str = cluster_info["cluster"]["endpoint"]
    ca_cert_b64: str = cluster_info["cluster"]["certificateAuthority"]["data"]

    # Configure Configuration
    configuration = Configuration()
    configuration.host = endpoint
    configuration.ssl_ca_cert = _write_ca_cert(ca_cert_b64)

    # Set initial token; STS presigned URL creation is synchronous
    token = await asyncio.to_thread(
        _generate_eks_token,
        session,
        cluster.cluster_name,
        cluster.region,
    )
    configuration.api_key["BearerToken"] = f"Bearer {token}"

    # refresh hook: automatic refresh before token expiration
    cluster_name = cluster.cluster_name
    region = cluster.region

    def _refresh_eks_token(config: Configuration) -> None:
        """Refresh token automatically."""
        new_token = _generate_eks_token(session, cluster_name, region)
        config.api_key["BearerToken"] = f"Bearer {new_token}"

    configuration.refresh_api_key_hook = _refresh_eks_token  # pyright: ignore[reportAttributeAccessIssue]  # kubernetes_asyncio library actually passes Configuration, but stub declares ApiClient

    if proxy_url:
        configuration.proxy = proxy_url

    return ApiClient(configuration=configuration)


# ---------------------------------------------------------------------------
# GKE authentication
# ---------------------------------------------------------------------------


def _get_gke_cluster_info(
    credentials: service_account.Credentials,
    project_id: str,
    cluster_name: str,
    location: str,
) -> GkeClusterInfo:
    """Fetch cluster endpoint and CA cert with GKE API.

    :param credentials: google-auth credentials object
    :param project_id: GCP project ID
    :param cluster_name: GKE cluster name
    :param location: GKE cluster location (region or zone)
    :return: (endpoint, ca_cert_base64) tuple
    :raises ValueError: On API call failure
    """
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)

    url = (
        f"https://container.googleapis.com/v1/projects/{project_id}"
        f"/locations/{location}/clusters/{cluster_name}"
    )

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {credentials.token}")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as resp:  # noqa: S310
        data = json.loads(resp.read().decode())

    endpoint: str = f"https://{data['endpoint']}"
    ca_cert_b64: str = data["masterAuth"]["clusterCaCertificate"]
    return GkeClusterInfo(endpoint=endpoint, ca_cert_b64=ca_cert_b64)


async def _create_gke_client(
    cluster: ClusterConfig,
    credential: GkeCredential,
    proxy_url: str | None,
) -> ApiClient:
    """Create ApiClient for GKE cluster.

    1. Create credentials from Service Account key
    2. Fetch endpoint + CA cert with GKE API
    3. Configure automatic refresh with refresh_api_key_hook
    4. Configure SSRF prevention proxy

    Wrap synchronous GCP calls with to_thread to avoid blocking event loop.

    :param cluster: Cluster settings
    :param credential: GKE credential
    :param proxy_url: egress proxy URL
    :return: Configured ApiClient
    :raises ValueError: When required field is absent
    """
    if not cluster.cluster_name:
        msg = "cluster_name is required for GKE authentication"
        raise ValueError(msg)
    if not cluster.region:
        msg = "region is required for GKE authentication"
        raise ValueError(msg)
    if not cluster.project_id:
        msg = "project_id is required for GKE authentication"
        raise ValueError(msg)

    # Create credentials from Service Account key
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = service_account.Credentials.from_service_account_info(
        credential.service_account_key,
        scopes=scopes,
    )

    # Fetch endpoint + CA cert with GKE API; HTTP call is synchronous, so use to_thread
    cluster_info = await asyncio.to_thread(
        _get_gke_cluster_info,
        credentials,
        cluster.project_id,
        cluster.cluster_name,
        cluster.region,
    )

    # Configure Configuration
    configuration = Configuration()
    configuration.host = cluster_info.endpoint
    configuration.ssl_ca_cert = _write_ca_cert(cluster_info.ca_cert_b64)

    # Set initial token
    configuration.api_key["BearerToken"] = f"Bearer {credentials.token}"

    # refresh hook: automatic refresh before token expiration
    def _refresh_gke_token(api_client: ApiClient) -> None:
        """Refresh token automatically."""
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        api_client.configuration.api_key["BearerToken"] = f"Bearer {credentials.token}"

    configuration.refresh_api_key_hook = _refresh_gke_token

    if proxy_url:
        configuration.proxy = proxy_url

    return ApiClient(configuration=configuration)


# ---------------------------------------------------------------------------
# ApiClient creation
# ---------------------------------------------------------------------------


async def create_exec_api_client(
    cluster_config: ClusterConfig,
    credential: (
        KubeconfigCredential | TokenCredential | EksCredential | GkeCredential
    ),
    *,
    proxy_url: str | None = None,
) -> ApiClient:
    """Create ApiClient according to authentication type.

    When proxy_url is set, route through proxy for SSRF prevention. Return async
    ApiClient based on kubernetes_asyncio.

    :param cluster_config: Cluster settings
    :param credential: Cluster authentication information
    :param proxy_url: egress proxy URL; direct connection when None
    :return: Configured ApiClient
    :raises ValueError: kubeconfig has exec provider or required field is absent
    :raises TypeError: When credential type is unknown
    """
    if isinstance(credential, KubeconfigCredential):
        kubeconfig_dict = yaml.safe_load(credential.kubeconfig_yaml)
        validate_kubeconfig(kubeconfig_dict)
        api_client = await new_client_from_config_dict(
            config_dict=kubeconfig_dict,
            context=cluster_config.context,
        )
        if proxy_url:
            api_client.configuration.proxy = proxy_url
        return api_client

    if isinstance(credential, TokenCredential):
        if not cluster_config.api_server:
            msg = "api_server is required for token authentication"
            raise ValueError(msg)
        configuration = Configuration()
        configuration.host = cluster_config.api_server
        configuration.api_key["BearerToken"] = f"Bearer {credential.token}"
        if credential.ca_cert:
            configuration.ssl_ca_cert = _write_ca_cert(credential.ca_cert)
        if proxy_url:
            configuration.proxy = proxy_url
        return ApiClient(configuration=configuration)

    if isinstance(credential, EksCredential):
        return await _create_eks_client(cluster_config, credential, proxy_url)

    if isinstance(credential, GkeCredential):
        return await _create_gke_client(cluster_config, credential, proxy_url)

    msg = f"Unknown credential type: {type(credential).__name__}"
    raise TypeError(msg)


# ---------------------------------------------------------------------------
# lightkube AsyncClient creation
# ---------------------------------------------------------------------------


async def create_lightkube_client(
    cluster_config: ClusterConfig,
    credential: (
        KubeconfigCredential | TokenCredential | EksCredential | GkeCredential
    ),
    *,
    proxy_url: str | None = None,
) -> AsyncClient:
    """Create lightkube AsyncClient according to authentication type.

    Used by Toolkit tools (list, get, logs, events, apply, delete, api-resources).
    exec tool requires WebSocket, so use create_exec_api_client().

    :param cluster_config: Cluster settings
    :param credential: Cluster authentication information
    :param proxy_url: egress proxy URL; direct connection when None
    :return: Configured lightkube AsyncClient
    :raises ValueError: When required field is absent or kubeconfig has exec provider
    :raises TypeError: When credential type is unknown
    """
    if isinstance(credential, KubeconfigCredential):
        kubeconfig_dict = yaml.safe_load(credential.kubeconfig_yaml)
        validate_kubeconfig(kubeconfig_dict)
        config = KubeConfig.from_dict(kubeconfig_dict)
        return AsyncClient(config=config, proxy=proxy_url)

    if isinstance(credential, TokenCredential):
        if not cluster_config.api_server:
            msg = "api_server is required for token authentication"
            raise ValueError(msg)
        lk_cluster = LightkubeCluster(server=cluster_config.api_server)
        if credential.ca_cert:
            lk_cluster = LightkubeCluster(
                server=cluster_config.api_server,
                certificate_auth_data=credential.ca_cert,
            )
        config = KubeConfig.from_one(
            cluster=lk_cluster,
            user=LightkubeUser(token=credential.token),
        )
        return AsyncClient(config=config, proxy=proxy_url)

    if isinstance(credential, EksCredential):
        return await _create_lightkube_eks_client(cluster_config, credential, proxy_url)

    if isinstance(credential, GkeCredential):
        return await _create_lightkube_gke_client(cluster_config, credential, proxy_url)

    msg = f"Unknown credential type: {type(credential).__name__}"
    raise TypeError(msg)


async def _create_lightkube_eks_client(
    cluster: ClusterConfig,
    credential: EksCredential,
    proxy_url: str | None,
) -> AsyncClient:
    """Create lightkube AsyncClient for EKS cluster.

    :param cluster: Cluster settings
    :param credential: EKS credential
    :param proxy_url: egress proxy URL
    :return: Configured lightkube AsyncClient
    """
    if not cluster.cluster_name:
        msg = "cluster_name is required for EKS authentication"
        raise ValueError(msg)
    if not cluster.region:
        msg = "region is required for EKS authentication"
        raise ValueError(msg)

    # Create boto3 session
    session = boto3.Session(
        aws_access_key_id=credential.aws_access_key_id,
        aws_secret_access_key=credential.aws_secret_access_key,
        region_name=cluster.region,
    )

    if credential.role_arn:
        assumed = await asyncio.to_thread(
            _assume_role_sync, session, credential.role_arn
        )
        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=cluster.region,
        )

    # Fetch endpoint + CA cert with describe_cluster
    cluster_info = await asyncio.to_thread(
        _describe_eks_cluster_sync, session, cluster.cluster_name, cluster.region
    )
    endpoint: str = cluster_info["cluster"]["endpoint"]
    ca_cert_b64: str = cluster_info["cluster"]["certificateAuthority"]["data"]

    # Issue token
    token = await asyncio.to_thread(
        _generate_eks_token, session, cluster.cluster_name, cluster.region
    )

    config = KubeConfig.from_one(
        cluster=LightkubeCluster(server=endpoint, certificate_auth_data=ca_cert_b64),
        user=LightkubeUser(token=token),
    )
    return AsyncClient(config=config, proxy=proxy_url)


async def _create_lightkube_gke_client(
    cluster: ClusterConfig,
    credential: GkeCredential,
    proxy_url: str | None,
) -> AsyncClient:
    """Create lightkube AsyncClient for GKE cluster.

    :param cluster: Cluster settings
    :param credential: GKE credential
    :param proxy_url: egress proxy URL
    :return: Configured lightkube AsyncClient
    """
    if not cluster.cluster_name:
        msg = "cluster_name is required for GKE authentication"
        raise ValueError(msg)
    if not cluster.region:
        msg = "region is required for GKE authentication"
        raise ValueError(msg)
    if not cluster.project_id:
        msg = "project_id is required for GKE authentication"
        raise ValueError(msg)

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = service_account.Credentials.from_service_account_info(
        credential.service_account_key, scopes=scopes
    )

    cluster_info = await asyncio.to_thread(
        _get_gke_cluster_info,
        credentials,
        cluster.project_id,
        cluster.cluster_name,
        cluster.region,
    )

    # Initial token; credentials.refresh() was already called in _get_gke_cluster_info
    token = credentials.token
    if token is None:
        msg = "Failed to obtain GKE access token"
        raise ValueError(msg)

    config = KubeConfig.from_one(
        cluster=LightkubeCluster(
            server=cluster_info.endpoint,
            certificate_auth_data=cluster_info.ca_cert_b64,
        ),
        user=LightkubeUser(token=token),
    )
    return AsyncClient(config=config, proxy=proxy_url)


# ---------------------------------------------------------------------------
# Cluster scan
# ---------------------------------------------------------------------------


async def scan_eks_clusters(
    credential: EksCredential,
    region: str | None = None,
) -> list[dict[str, str | None]]:
    """Scan EKS clusters and return list.

    Wrap synchronous boto3 calls with to_thread to avoid blocking event loop.

    :param credential: EKS credential
    :param region: AWS region; use default region when None
    :return: List of cluster info dicts
    """
    return await asyncio.to_thread(
        _scan_eks_clusters_sync,
        credential,
        region,
    )


def _scan_eks_clusters_sync(
    credential: EksCredential,
    region: str | None,
) -> list[dict[str, str | None]]:
    """Synchronous implementation of EKS cluster scan. Used from asyncio.to_thread.

    :param credential: EKS credential
    :param region: AWS region
    :return: List of cluster info dicts
    """
    session = boto3.Session(
        aws_access_key_id=credential.aws_access_key_id,
        aws_secret_access_key=credential.aws_secret_access_key,
        region_name=region,
    )

    # assume role (optional)
    if credential.role_arn:
        sts = session.client("sts")
        assumed = sts.assume_role(
            RoleArn=credential.role_arn,
            RoleSessionName="azents-k8s-scan",
        )
        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )

    eks_client = session.client("eks", region_name=region)

    # Fetch cluster list
    cluster_names: list[str] = eks_client.list_clusters()["clusters"]

    # Fetch details for each cluster
    result: list[dict[str, str | None]] = []
    for name in cluster_names:
        info = eks_client.describe_cluster(name=name)
        cluster_data = info["cluster"]
        result.append(
            {
                "name": cluster_data["name"],
                "region": region or session.region_name,
                "status": cluster_data.get("status", "UNKNOWN"),
                "endpoint": cluster_data.get("endpoint"),
                "version": cluster_data.get("version"),
            }
        )

    return result


async def scan_gke_clusters(
    credential: GkeCredential,
    project_id: str,
) -> list[dict[str, str]]:
    """Scan GKE clusters and return list.

    Wrap synchronous GCP calls with to_thread to avoid blocking event loop.

    :param credential: GKE credential
    :param project_id: GCP project ID
    :return: List of cluster info dicts
    """
    return await asyncio.to_thread(
        _scan_gke_clusters_sync,
        credential,
        project_id,
    )


def _scan_gke_clusters_sync(
    credential: GkeCredential,
    project_id: str,
) -> list[dict[str, str]]:
    """Synchronous implementation of GKE cluster scan. Used from asyncio.to_thread.

    :param credential: GKE credential
    :param project_id: GCP project ID
    :return: List of cluster info dicts
    """
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = service_account.Credentials.from_service_account_info(
        credential.service_account_key,
        scopes=scopes,
    )

    request = google.auth.transport.requests.Request()
    credentials.refresh(request)

    # Fetch all clusters with GKE API
    url = (
        f"https://container.googleapis.com/v1/projects/{project_id}"
        "/locations/-/clusters"
    )

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {credentials.token}")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as resp:  # noqa: S310
        data = json.loads(resp.read().decode())

    result: list[dict[str, str]] = []
    for cluster_data in data.get("clusters", []):
        result.append(
            {
                "name": cluster_data["name"],
                "region": cluster_data.get("location", ""),
                "status": cluster_data.get("status", "UNKNOWN"),
                "endpoint": cluster_data.get("endpoint", ""),
                "version": cluster_data.get("currentMasterVersion", ""),
            }
        )

    return result
