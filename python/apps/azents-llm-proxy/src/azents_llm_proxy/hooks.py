"""Official Proxy/deployment hooks tied to the outer ASGI request scope."""

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from litellm.caching.caching import DualCache
from litellm.integrations.custom_logger import CustomLogger
from litellm.proxy._types import ProxyException, UserAPIKeyAuth
from litellm.types.utils import CallTypes, CallTypesLiteral

from azents_llm_proxy.context import RequestContext
from azents_llm_proxy.egress import ProviderClient
from azents_llm_proxy.errors import safe_failure
from azents_llm_proxy.history import bridge_image_history
from azents_llm_proxy.native import native_corrections
from azents_llm_proxy.provider import (
    ProviderConfigurationError,
    provider_invocation,
    uses_chat_bridge,
)
from azents_llm_proxy.settings import (
    FidelityUnavailable,
    UnsupportedRequest,
    normalize_request,
)
from azents_llm_proxy.tools import ToolCompilation, bridge_controls, compile_tools


@dataclass(frozen=True, repr=False)
class ApprovedInvocation:
    arguments: dict[str, object]
    tools: ToolCompilation
    client: ProviderClient


class InvocationBoundary(CustomLogger):
    def __init__(self, context: RequestContext) -> None:
        super().__init__()
        self.context = context

    async def async_log_success_event(
        self,
        kwargs: dict,
        response_obj: object,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        self.observe(kwargs, response_obj, start_time, end_time, success=True)

    async def async_log_failure_event(
        self,
        kwargs: dict,
        response_obj: object,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        self.observe(kwargs, response_obj, start_time, end_time, success=False)

    def observe(
        self,
        kwargs: dict,
        response: object,
        start: datetime,
        end: datetime,
        *,
        success: bool,
    ) -> None:
        # Nested Responses-to-Chat calls do not create duplicate operations.
        if kwargs.get("call_type") not in {"aresponses", "responses"}:
            return
        state = self.context.current.get()
        if state is not None and state.operation is not None:
            state.operation.emit(
                outcome="success" if success else "failure",
                response=response,
                start=start,
                end=end,
            )

    def prepare(self) -> ApprovedInvocation:
        auth = self.context.require_auth()
        binding = auth.inference()
        try:
            payload = normalize_request(auth.selectors(), binding)
            tools = compile_tools(payload, binding)
            payload = tools.payload
            if uses_chat_bridge(binding):
                payload = bridge_image_history(payload)
            invocation = provider_invocation(binding)
            client = self.context.client_for(binding, invocation)
        except UnsupportedRequest:
            raise ProxyException(
                message="Requested feature is unavailable for this target.",
                type="invalid_request_error",
                param="request",
                code=400,
            ) from None
        except FidelityUnavailable, ProviderConfigurationError:
            raise ProxyException(
                message="Provider preparation is unavailable.",
                type="service_unavailable_error",
                param="azents_authority",
                code=503,
            ) from None
        approved: dict[str, object] = {
            **payload,
            **invocation.arguments,
            "num_retries": 0,
            "max_retries": 0,
            "caching": False,
            "drop_params": False,
        }
        corrections = native_corrections(payload, binding.credential)
        if tools.native_response_tools is not None:
            if corrections is None:
                corrections = {}
            corrections["tools"] = tools.native_response_tools
        if corrections is not None:
            approved["extra_body"] = corrections
        return ApprovedInvocation(arguments=approved, tools=tools, client=client)

    def approved(self) -> dict[str, object]:
        return self.prepare().arguments

    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: CallTypesLiteral,
    ) -> dict:
        if call_type != "aresponses":
            raise ProxyException(
                message="Operation is not available to Agent credentials.",
                type="permission_error",
                param="route",
                code=403,
            )
        # Keep upstream accounting objects, but replace the entire caller payload
        # with the ingress-validated request and approved provider arguments.
        approved = self.approved()
        for key in self.context.require_auth().selectors().payload:
            data.pop(key, None)
        data.update(approved)
        return data

    async def async_pre_call_deployment_hook(
        self, kwargs: dict[str, object], call_type: CallTypes | None
    ) -> dict[str, object]:
        binding = self.context.require_auth().inference()
        bridge_call = call_type == CallTypes.acompletion and uses_chat_bridge(binding)
        if call_type != CallTypes.aresponses and not bridge_call:
            raise ProxyException(
                message="Provider translation is not verified for this target.",
                type="service_unavailable_error",
                param="azents_authority",
                code=503,
            )
        prepared = self.prepare()
        approved = prepared.arguments
        if bridge_call:
            # LiteLLM owns Responses-to-Chat content/setting translation. At the
            # second physical boundary the exact approved route/account still
            # must hold; there is no Router, override or fallback authority.
            invocation = provider_invocation(binding)
            approved = dict(invocation.arguments)
            expected_provider = invocation.arguments["model"].split("/", maxsplit=1)[0]
            provider = kwargs.get("custom_llm_provider")
            if provider is not None and provider != expected_provider:
                raise ProxyException(
                    message="Approved inference provider changed before dispatch.",
                    type="permission_error",
                    param="azents_authority",
                    code=403,
                )
            if provider is not None:
                approved["custom_llm_provider"] = provider
            # The SDK strips only its own provider qualification before its
            # internal Chat call. The exact stored model is valid only with the
            # same explicit provider; no model normalization or alias is allowed.
            if (
                provider == expected_provider
                and kwargs.get("model") == binding.model_identifier
            ):
                approved["model"] = binding.model_identifier
            approved.update(
                {
                    "num_retries": 0,
                    "max_retries": 0,
                    "caching": False,
                    "drop_params": False,
                }
            )
            try:
                controls = bridge_controls(prepared.tools, kwargs.get("tools"))
            except FidelityUnavailable:
                raise ProxyException(
                    message="Provider tool preparation is unavailable.",
                    type="service_unavailable_error",
                    param="azents_authority",
                    code=503,
                ) from None
            if controls:
                if prepared.tools.anthropic_search is not None:
                    # Replace only the bridge's derived lossy search option
                    # with the complete typed native declaration.
                    kwargs.pop("web_search_options", None)
                if "extra_body" in controls and kwargs.get("extra_body") not in (
                    None,
                    {},
                ):
                    raise ProxyException(
                        message="Unapproved provider body reached dispatch.",
                        type="permission_error",
                        param="azents_authority",
                        code=403,
                    )
                kwargs.update(controls)
                approved.update(controls)
        existing_client = kwargs.get("client")
        if existing_client is not None and existing_client is not prepared.client:
            raise ProxyException(
                message="Unapproved inference client reached dispatch.",
                type="permission_error",
                param="azents_authority",
                code=403,
            )
        kwargs["client"] = prepared.client
        approved["client"] = prepared.client
        closed_controls = {
            "client",
            "api_key",
            "api_base",
            "base_url",
            "api_version",
            "extra_headers",
            "extra_body",
            "headers",
            "custom_llm_provider",
            "credential_name",
            "litellm_credential_name",
            "user_config",
            "fallbacks",
            "context_window_fallbacks",
            "content_policy_fallbacks",
            "mock_response",
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
            "aws_profile_name",
            "aws_role_name",
            "aws_session_name",
            "aws_web_identity_token",
            "aws_region_name",
            "aws_bedrock_runtime_endpoint",
            "vertex_credentials",
            "vertex_project",
            "vertex_location",
        }
        if any(
            key in kwargs and kwargs[key] is not None and key not in approved
            for key in closed_controls
        ):
            raise ProxyException(
                message="Unapproved provider control reached dispatch.",
                type="permission_error",
                param="azents_authority",
                code=403,
            )
        for key, value in approved.items():
            if kwargs.get(key) != value:
                raise ProxyException(
                    message="Approved inference invocation changed before dispatch.",
                    type="permission_error",
                    param="azents_authority",
                    code=403,
                )
        return kwargs

    async def async_post_call_failure_hook(
        self,
        request_data: dict,
        original_exception: Exception,
        user_api_key_dict: UserAPIKeyAuth,
        traceback_str: str | None = None,
    ) -> HTTPException:
        scope = self.context.current.get()
        return safe_failure(
            original_exception,
            authority_pending=scope is None or scope.auth is None,
        )
