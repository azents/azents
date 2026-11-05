"""Online, audience-bound Kubernetes resolver identity verification."""

from dataclasses import dataclass

from aiohttp import ClientError
from kubernetes_asyncio.client import AuthenticationV1Api
from kubernetes_asyncio.client.models.v1_token_review import V1TokenReview
from kubernetes_asyncio.client.models.v1_token_review_spec import V1TokenReviewSpec
from kubernetes_asyncio.client.rest import ApiException

RESOLVER_AUDIENCE = "azents-llm-resolver"


@dataclass(frozen=True)
class KubernetesResolverAuth:
    """Accept only the configured workload under the resolver audience."""

    api: AuthenticationV1Api
    subject: str

    async def accepts(self, token: str) -> bool:
        try:
            result = await self.api.create_token_review(
                V1TokenReview(
                    spec=V1TokenReviewSpec(token=token, audiences=[RESOLVER_AUDIENCE])
                ),
                _request_timeout=10,
            )
        except ApiException, ClientError, TimeoutError:
            raise RuntimeError(
                "Resolver identity verification is unavailable."
            ) from None
        status = result.status
        return bool(
            status is not None
            and status.authenticated is True
            and RESOLVER_AUDIENCE in (status.audiences or ())
            and status.user is not None
            and status.user.username == self.subject
        )
