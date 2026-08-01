# azentspublicclient.ExternalChannelV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**external_channel_v1_add_multi_discord_route**](ExternalChannelV1Api.md#external_channel_v1_add_multi_discord_route) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/agents | Add Multi Discord Route
[**external_channel_v1_add_multi_slack_route**](ExternalChannelV1Api.md#external_channel_v1_add_multi_slack_route) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents | Add Multi Slack Route
[**external_channel_v1_clear_multi_discord_channel_default**](ExternalChannelV1Api.md#external_channel_v1_clear_multi_discord_channel_default) | **DELETE** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/channel-defaults/{provider_channel_id} | Clear Multi Discord Channel Default
[**external_channel_v1_clear_multi_slack_channel_default**](ExternalChannelV1Api.md#external_channel_v1_clear_multi_slack_channel_default) | **DELETE** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/channel-defaults/{provider_channel_id} | Clear Multi Slack Channel Default
[**external_channel_v1_decide_approval_request**](ExternalChannelV1Api.md#external_channel_v1_decide_approval_request) | **POST** /external-channel/v1/approval-requests/{access_request_id}/decision | Decide Approval Request
[**external_channel_v1_disconnect_connection**](ExternalChannelV1Api.md#external_channel_v1_disconnect_connection) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id} | Disconnect Connection
[**external_channel_v1_disconnect_multi_discord_connection**](ExternalChannelV1Api.md#external_channel_v1_disconnect_multi_discord_connection) | **DELETE** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id} | Disconnect Multi Discord Connection
[**external_channel_v1_disconnect_multi_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_disconnect_multi_slack_connection) | **DELETE** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id} | Disconnect Multi Slack Connection
[**external_channel_v1_disconnect_session_channel**](ExternalChannelV1Api.md#external_channel_v1_disconnect_session_channel) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels/{binding_id} | Disconnect Session Channel
[**external_channel_v1_get_approval_request**](ExternalChannelV1Api.md#external_channel_v1_get_approval_request) | **GET** /external-channel/v1/approval-requests/{access_request_id} | Get Approval Request
[**external_channel_v1_get_manifest_guidance**](ExternalChannelV1Api.md#external_channel_v1_get_manifest_guidance) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/manifest | Get Manifest Guidance
[**external_channel_v1_get_multi_discord_connection**](ExternalChannelV1Api.md#external_channel_v1_get_multi_discord_connection) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id} | Get Multi Discord Connection
[**external_channel_v1_get_multi_discord_connection_impact**](ExternalChannelV1Api.md#external_channel_v1_get_multi_discord_connection_impact) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/impact | Get Multi Discord Connection Impact
[**external_channel_v1_get_multi_discord_route_impact**](ExternalChannelV1Api.md#external_channel_v1_get_multi_discord_route_impact) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/agents/{route_id}/impact | Get Multi Discord Route Impact
[**external_channel_v1_get_multi_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_get_multi_slack_connection) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id} | Get Multi Slack Connection
[**external_channel_v1_get_multi_slack_connection_impact**](ExternalChannelV1Api.md#external_channel_v1_get_multi_slack_connection_impact) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/impact | Get Multi Slack Connection Impact
[**external_channel_v1_get_multi_slack_route_impact**](ExternalChannelV1Api.md#external_channel_v1_get_multi_slack_route_impact) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents/{route_id}/impact | Get Multi Slack Route Impact
[**external_channel_v1_list_agent_access**](ExternalChannelV1Api.md#external_channel_v1_list_agent_access) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access | List Agent Access
[**external_channel_v1_list_connections**](ExternalChannelV1Api.md#external_channel_v1_list_connections) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels | List Connections
[**external_channel_v1_list_multi_connections**](ExternalChannelV1Api.md#external_channel_v1_list_multi_connections) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/multi | List Multi Connections
[**external_channel_v1_list_multi_discord_channel_defaults**](ExternalChannelV1Api.md#external_channel_v1_list_multi_discord_channel_defaults) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/channel-defaults | List Multi Discord Channel Defaults
[**external_channel_v1_list_multi_discord_connections**](ExternalChannelV1Api.md#external_channel_v1_list_multi_discord_connections) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi | List Multi Discord Connections
[**external_channel_v1_list_multi_discord_routes**](ExternalChannelV1Api.md#external_channel_v1_list_multi_discord_routes) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/agents | List Multi Discord Routes
[**external_channel_v1_list_multi_slack_channel_defaults**](ExternalChannelV1Api.md#external_channel_v1_list_multi_slack_channel_defaults) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/channel-defaults | List Multi Slack Channel Defaults
[**external_channel_v1_list_multi_slack_connections**](ExternalChannelV1Api.md#external_channel_v1_list_multi_slack_connections) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi | List Multi Slack Connections
[**external_channel_v1_list_multi_slack_routes**](ExternalChannelV1Api.md#external_channel_v1_list_multi_slack_routes) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents | List Multi Slack Routes
[**external_channel_v1_list_session_channels**](ExternalChannelV1Api.md#external_channel_v1_list_session_channels) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels | List Session Channels
[**external_channel_v1_load_multi_slack_management_handoff**](ExternalChannelV1Api.md#external_channel_v1_load_multi_slack_management_handoff) | **GET** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/management-handoffs/{interaction_id} | Load Multi Slack Management Handoff
[**external_channel_v1_reenable_multi_discord_route**](ExternalChannelV1Api.md#external_channel_v1_reenable_multi_discord_route) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/agents/{route_id}/reenable | Reenable Multi Discord Route
[**external_channel_v1_reenable_multi_slack_route**](ExternalChannelV1Api.md#external_channel_v1_reenable_multi_slack_route) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents/{route_id}/reenable | Reenable Multi Slack Route
[**external_channel_v1_remove_access_block**](ExternalChannelV1Api.md#external_channel_v1_remove_access_block) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access/blocks/{block_id} | Remove Access Block
[**external_channel_v1_remove_multi_discord_route**](ExternalChannelV1Api.md#external_channel_v1_remove_multi_discord_route) | **DELETE** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/agents/{route_id} | Remove Multi Discord Route
[**external_channel_v1_remove_multi_slack_route**](ExternalChannelV1Api.md#external_channel_v1_remove_multi_slack_route) | **DELETE** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents/{route_id} | Remove Multi Slack Route
[**external_channel_v1_replace_multi_discord_channel_default**](ExternalChannelV1Api.md#external_channel_v1_replace_multi_discord_channel_default) | **PUT** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/channel-defaults/{provider_channel_id} | Replace Multi Discord Channel Default
[**external_channel_v1_replace_multi_slack_channel_default**](ExternalChannelV1Api.md#external_channel_v1_replace_multi_slack_channel_default) | **PUT** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/channel-defaults/{provider_channel_id} | Replace Multi Slack Channel Default
[**external_channel_v1_revoke_access_grant**](ExternalChannelV1Api.md#external_channel_v1_revoke_access_grant) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access/grants/{grant_id} | Revoke Access Grant
[**external_channel_v1_setup_discord_connection**](ExternalChannelV1Api.md#external_channel_v1_setup_discord_connection) | **POST** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/discord | Setup Discord Connection
[**external_channel_v1_setup_multi_discord_connection**](ExternalChannelV1Api.md#external_channel_v1_setup_multi_discord_connection) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi | Setup Multi Discord Connection
[**external_channel_v1_setup_multi_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_setup_multi_slack_connection) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi | Setup Multi Slack Connection
[**external_channel_v1_setup_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_setup_slack_connection) | **POST** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/slack | Setup Slack Connection
[**external_channel_v1_update_connection_access_policy**](ExternalChannelV1Api.md#external_channel_v1_update_connection_access_policy) | **PUT** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/access-policy | Update Connection Access Policy
[**external_channel_v1_update_discord_connection**](ExternalChannelV1Api.md#external_channel_v1_update_discord_connection) | **PUT** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/discord | Update Discord Connection
[**external_channel_v1_update_multi_discord_connection**](ExternalChannelV1Api.md#external_channel_v1_update_multi_discord_connection) | **PUT** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id} | Update Multi Discord Connection
[**external_channel_v1_update_multi_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_update_multi_slack_connection) | **PUT** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id} | Update Multi Slack Connection
[**external_channel_v1_update_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_update_slack_connection) | **PUT** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/slack | Update Slack Connection
[**external_channel_v1_validate_connection**](ExternalChannelV1Api.md#external_channel_v1_validate_connection) | **POST** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/validate | Validate Connection
[**external_channel_v1_validate_multi_discord_connection**](ExternalChannelV1Api.md#external_channel_v1_validate_multi_discord_connection) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}/validate | Validate Multi Discord Connection
[**external_channel_v1_validate_multi_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_validate_multi_slack_connection) | **POST** /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/validate | Validate Multi Slack Connection


# **external_channel_v1_add_multi_discord_route**
> ManagedMultiRoute external_channel_v1_add_multi_discord_route(connection_id, handle, multi_route_create_request)

Add Multi Discord Route

Add one active Workspace Agent to a Discord Multi App catalog.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_route import ManagedMultiRoute
from azentspublicclient.models.multi_route_create_request import MultiRouteCreateRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    multi_route_create_request = azentspublicclient.MultiRouteCreateRequest() # MultiRouteCreateRequest | 

    try:
        # Add Multi Discord Route
        api_response = api_instance.external_channel_v1_add_multi_discord_route(connection_id, handle, multi_route_create_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_add_multi_discord_route:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_add_multi_discord_route: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **multi_route_create_request** | [**MultiRouteCreateRequest**](MultiRouteCreateRequest.md)|  | 

### Return type

[**ManagedMultiRoute**](ManagedMultiRoute.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_add_multi_slack_route**
> ManagedMultiRoute external_channel_v1_add_multi_slack_route(connection_id, handle, multi_route_create_request)

Add Multi Slack Route

Add one active Workspace Agent to a Slack Multi App catalog.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_route import ManagedMultiRoute
from azentspublicclient.models.multi_route_create_request import MultiRouteCreateRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    multi_route_create_request = azentspublicclient.MultiRouteCreateRequest() # MultiRouteCreateRequest | 

    try:
        # Add Multi Slack Route
        api_response = api_instance.external_channel_v1_add_multi_slack_route(connection_id, handle, multi_route_create_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_add_multi_slack_route:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_add_multi_slack_route: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **multi_route_create_request** | [**MultiRouteCreateRequest**](MultiRouteCreateRequest.md)|  | 

### Return type

[**ManagedMultiRoute**](ManagedMultiRoute.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_clear_multi_discord_channel_default**
> external_channel_v1_clear_multi_discord_channel_default(connection_id, provider_channel_id, handle, generation_fence_request)

Clear Multi Discord Channel Default

Generation-fence clearing one active Multi App channel default.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    provider_channel_id = 'provider_channel_id_example' # str | 
    handle = 'handle_example' # str | 
    generation_fence_request = azentspublicclient.GenerationFenceRequest() # GenerationFenceRequest | 

    try:
        # Clear Multi Discord Channel Default
        api_instance.external_channel_v1_clear_multi_discord_channel_default(connection_id, provider_channel_id, handle, generation_fence_request)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_clear_multi_discord_channel_default: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **provider_channel_id** | **str**|  | 
 **handle** | **str**|  | 
 **generation_fence_request** | [**GenerationFenceRequest**](GenerationFenceRequest.md)|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_clear_multi_slack_channel_default**
> external_channel_v1_clear_multi_slack_channel_default(connection_id, provider_channel_id, handle, generation_fence_request)

Clear Multi Slack Channel Default

Generation-fence clearing one active Multi App channel default.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    provider_channel_id = 'provider_channel_id_example' # str | 
    handle = 'handle_example' # str | 
    generation_fence_request = azentspublicclient.GenerationFenceRequest() # GenerationFenceRequest | 

    try:
        # Clear Multi Slack Channel Default
        api_instance.external_channel_v1_clear_multi_slack_channel_default(connection_id, provider_channel_id, handle, generation_fence_request)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_clear_multi_slack_channel_default: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **provider_channel_id** | **str**|  | 
 **handle** | **str**|  | 
 **generation_fence_request** | [**GenerationFenceRequest**](GenerationFenceRequest.md)|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_decide_approval_request**
> ManagedApprovalRequest external_channel_v1_decide_approval_request(access_request_id, external_channel_decision_input)

Decide Approval Request

Apply one idempotent Allow Session, Allow Agent, Deny, or Block decision.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_decision_input import ExternalChannelDecisionInput
from azentspublicclient.models.managed_approval_request import ManagedApprovalRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    access_request_id = 'access_request_id_example' # str | 
    external_channel_decision_input = azentspublicclient.ExternalChannelDecisionInput() # ExternalChannelDecisionInput | 

    try:
        # Decide Approval Request
        api_response = api_instance.external_channel_v1_decide_approval_request(access_request_id, external_channel_decision_input)
        print("The response of ExternalChannelV1Api->external_channel_v1_decide_approval_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_decide_approval_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **access_request_id** | **str**|  | 
 **external_channel_decision_input** | [**ExternalChannelDecisionInput**](ExternalChannelDecisionInput.md)|  | 

### Return type

[**ManagedApprovalRequest**](ManagedApprovalRequest.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_disconnect_connection**
> ManagedConnection external_channel_v1_disconnect_connection(agent_id, connection_id, handle)

Disconnect Connection

Terminally disconnect a connection after one-attempt provider cleanup.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_connection import ManagedConnection
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Disconnect Connection
        api_response = api_instance.external_channel_v1_disconnect_connection(agent_id, connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_disconnect_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_disconnect_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedConnection**](ManagedConnection.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_disconnect_multi_discord_connection**
> ManagedMultiConnectionDisconnect external_channel_v1_disconnect_multi_discord_connection(connection_id, handle, generation_fence_request)

Disconnect Multi Discord Connection

Generation-fence terminal disconnect of one Workspace Discord Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest
from azentspublicclient.models.managed_multi_connection_disconnect import ManagedMultiConnectionDisconnect
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    generation_fence_request = azentspublicclient.GenerationFenceRequest() # GenerationFenceRequest | 

    try:
        # Disconnect Multi Discord Connection
        api_response = api_instance.external_channel_v1_disconnect_multi_discord_connection(connection_id, handle, generation_fence_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_disconnect_multi_discord_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_disconnect_multi_discord_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **generation_fence_request** | [**GenerationFenceRequest**](GenerationFenceRequest.md)|  | 

### Return type

[**ManagedMultiConnectionDisconnect**](ManagedMultiConnectionDisconnect.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_disconnect_multi_slack_connection**
> ManagedMultiConnectionDisconnect external_channel_v1_disconnect_multi_slack_connection(connection_id, handle, generation_fence_request)

Disconnect Multi Slack Connection

Generation-fence terminal disconnect of one Workspace Slack Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest
from azentspublicclient.models.managed_multi_connection_disconnect import ManagedMultiConnectionDisconnect
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    generation_fence_request = azentspublicclient.GenerationFenceRequest() # GenerationFenceRequest | 

    try:
        # Disconnect Multi Slack Connection
        api_response = api_instance.external_channel_v1_disconnect_multi_slack_connection(connection_id, handle, generation_fence_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_disconnect_multi_slack_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_disconnect_multi_slack_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **generation_fence_request** | [**GenerationFenceRequest**](GenerationFenceRequest.md)|  | 

### Return type

[**ManagedMultiConnectionDisconnect**](ManagedMultiConnectionDisconnect.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_disconnect_session_channel**
> ManagedBindingListResponse external_channel_v1_disconnect_session_channel(agent_id, session_id, binding_id, handle)

Disconnect Session Channel

Terminally disconnect one binding and retain its history.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_binding_list_response import ManagedBindingListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    binding_id = 'binding_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Disconnect Session Channel
        api_response = api_instance.external_channel_v1_disconnect_session_channel(agent_id, session_id, binding_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_disconnect_session_channel:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_disconnect_session_channel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **binding_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedBindingListResponse**](ManagedBindingListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_approval_request**
> ManagedApprovalRequest external_channel_v1_get_approval_request(access_request_id)

Get Approval Request

Load one opaque authenticated approval request.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_approval_request import ManagedApprovalRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    access_request_id = 'access_request_id_example' # str | 

    try:
        # Get Approval Request
        api_response = api_instance.external_channel_v1_get_approval_request(access_request_id)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_approval_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_approval_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **access_request_id** | **str**|  | 

### Return type

[**ManagedApprovalRequest**](ManagedApprovalRequest.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_manifest_guidance**
> SlackManifestGuidance external_channel_v1_get_manifest_guidance(agent_id, handle, transport, app_name=app_name)

Get Manifest Guidance

Return copy-ready Slack App configuration after Agent access validation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_transport import ExternalChannelTransport
from azentspublicclient.models.slack_manifest_guidance import SlackManifestGuidance
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    transport = azentspublicclient.ExternalChannelTransport() # ExternalChannelTransport | 
    app_name = 'Azents Agent' # str |  (optional) (default to 'Azents Agent')

    try:
        # Get Manifest Guidance
        api_response = api_instance.external_channel_v1_get_manifest_guidance(agent_id, handle, transport, app_name=app_name)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_manifest_guidance:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_manifest_guidance: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **transport** | [**ExternalChannelTransport**](.md)|  | 
 **app_name** | **str**|  | [optional] [default to &#39;Azents Agent&#39;]

### Return type

[**SlackManifestGuidance**](SlackManifestGuidance.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_multi_discord_connection**
> ManagedMultiConnection external_channel_v1_get_multi_discord_connection(connection_id, handle)

Get Multi Discord Connection

Load one redacted Workspace Discord Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_connection import ManagedMultiConnection
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Multi Discord Connection
        api_response = api_instance.external_channel_v1_get_multi_discord_connection(connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_multi_discord_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_multi_discord_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedMultiConnection**](ManagedMultiConnection.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_multi_discord_connection_impact**
> ExternalChannelMultiConnectionImpact external_channel_v1_get_multi_discord_connection_impact(connection_id, handle)

Get Multi Discord Connection Impact

Preview sanitized impact before disconnecting one whole Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_multi_connection_impact import ExternalChannelMultiConnectionImpact
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Multi Discord Connection Impact
        api_response = api_instance.external_channel_v1_get_multi_discord_connection_impact(connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_multi_discord_connection_impact:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_multi_discord_connection_impact: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ExternalChannelMultiConnectionImpact**](ExternalChannelMultiConnectionImpact.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_multi_discord_route_impact**
> ExternalChannelMultiRouteImpact external_channel_v1_get_multi_discord_route_impact(connection_id, route_id, handle)

Get Multi Discord Route Impact

Preview sanitized impact before removing one Multi App Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_multi_route_impact import ExternalChannelMultiRouteImpact
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    route_id = 'route_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Multi Discord Route Impact
        api_response = api_instance.external_channel_v1_get_multi_discord_route_impact(connection_id, route_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_multi_discord_route_impact:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_multi_discord_route_impact: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **route_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ExternalChannelMultiRouteImpact**](ExternalChannelMultiRouteImpact.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_multi_slack_connection**
> ManagedMultiConnection external_channel_v1_get_multi_slack_connection(connection_id, handle)

Get Multi Slack Connection

Load one redacted Workspace Slack Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_connection import ManagedMultiConnection
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Multi Slack Connection
        api_response = api_instance.external_channel_v1_get_multi_slack_connection(connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_multi_slack_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_multi_slack_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedMultiConnection**](ManagedMultiConnection.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_multi_slack_connection_impact**
> ExternalChannelMultiConnectionImpact external_channel_v1_get_multi_slack_connection_impact(connection_id, handle)

Get Multi Slack Connection Impact

Preview sanitized impact before disconnecting one whole Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_multi_connection_impact import ExternalChannelMultiConnectionImpact
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Multi Slack Connection Impact
        api_response = api_instance.external_channel_v1_get_multi_slack_connection_impact(connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_multi_slack_connection_impact:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_multi_slack_connection_impact: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ExternalChannelMultiConnectionImpact**](ExternalChannelMultiConnectionImpact.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_get_multi_slack_route_impact**
> ExternalChannelMultiRouteImpact external_channel_v1_get_multi_slack_route_impact(connection_id, route_id, handle)

Get Multi Slack Route Impact

Preview sanitized impact before removing one Multi App Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_multi_route_impact import ExternalChannelMultiRouteImpact
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    route_id = 'route_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Multi Slack Route Impact
        api_response = api_instance.external_channel_v1_get_multi_slack_route_impact(connection_id, route_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_get_multi_slack_route_impact:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_get_multi_slack_route_impact: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **route_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ExternalChannelMultiRouteImpact**](ExternalChannelMultiRouteImpact.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_agent_access**
> ManagedAccessResponse external_channel_v1_list_agent_access(agent_id, handle)

List Agent Access

List Agent grants and blocks without provider-native secret data.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_access_response import ManagedAccessResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # List Agent Access
        api_response = api_instance.external_channel_v1_list_agent_access(agent_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_agent_access:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_agent_access: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedAccessResponse**](ManagedAccessResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_connections**
> ManagedConnectionListResponse external_channel_v1_list_connections(agent_id, handle)

List Connections

List provider-neutral connections and routes for one Agent.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_connection_list_response import ManagedConnectionListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # List Connections
        api_response = api_instance.external_channel_v1_list_connections(agent_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_connections:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_connections: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedConnectionListResponse**](ManagedConnectionListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_multi_connections**
> ManagedMultiConnectionListResponse external_channel_v1_list_multi_connections(handle, offset=offset, limit=limit)

List Multi Connections

List Workspace-owned Multi Apps across providers in one stable page.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_connection_list_response import ManagedMultiConnectionListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Multi Connections
        api_response = api_instance.external_channel_v1_list_multi_connections(handle, offset=offset, limit=limit)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_multi_connections:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_multi_connections: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**ManagedMultiConnectionListResponse**](ManagedMultiConnectionListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_multi_discord_channel_defaults**
> ManagedChannelDefaultListResponse external_channel_v1_list_multi_discord_channel_defaults(connection_id, handle, offset=offset, limit=limit)

List Multi Discord Channel Defaults

List paged Multi App channel-default history.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_channel_default_list_response import ManagedChannelDefaultListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Multi Discord Channel Defaults
        api_response = api_instance.external_channel_v1_list_multi_discord_channel_defaults(connection_id, handle, offset=offset, limit=limit)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_multi_discord_channel_defaults:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_multi_discord_channel_defaults: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**ManagedChannelDefaultListResponse**](ManagedChannelDefaultListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_multi_discord_connections**
> ManagedMultiConnectionListResponse external_channel_v1_list_multi_discord_connections(handle, offset=offset, limit=limit)

List Multi Discord Connections

List Workspace-owned Discord Multi Apps.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_connection_list_response import ManagedMultiConnectionListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Multi Discord Connections
        api_response = api_instance.external_channel_v1_list_multi_discord_connections(handle, offset=offset, limit=limit)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_multi_discord_connections:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_multi_discord_connections: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**ManagedMultiConnectionListResponse**](ManagedMultiConnectionListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_multi_discord_routes**
> ManagedMultiRouteListResponse external_channel_v1_list_multi_discord_routes(connection_id, handle, offset=offset, limit=limit)

List Multi Discord Routes

List a paged Multi App Agent catalog, including removed routes.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_route_list_response import ManagedMultiRouteListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Multi Discord Routes
        api_response = api_instance.external_channel_v1_list_multi_discord_routes(connection_id, handle, offset=offset, limit=limit)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_multi_discord_routes:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_multi_discord_routes: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**ManagedMultiRouteListResponse**](ManagedMultiRouteListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_multi_slack_channel_defaults**
> ManagedChannelDefaultListResponse external_channel_v1_list_multi_slack_channel_defaults(connection_id, handle, offset=offset, limit=limit)

List Multi Slack Channel Defaults

List paged Multi App channel-default history.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_channel_default_list_response import ManagedChannelDefaultListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Multi Slack Channel Defaults
        api_response = api_instance.external_channel_v1_list_multi_slack_channel_defaults(connection_id, handle, offset=offset, limit=limit)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_multi_slack_channel_defaults:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_multi_slack_channel_defaults: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**ManagedChannelDefaultListResponse**](ManagedChannelDefaultListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_multi_slack_connections**
> ManagedMultiConnectionListResponse external_channel_v1_list_multi_slack_connections(handle, offset=offset, limit=limit)

List Multi Slack Connections

List Workspace-owned Slack Multi Apps.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_connection_list_response import ManagedMultiConnectionListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Multi Slack Connections
        api_response = api_instance.external_channel_v1_list_multi_slack_connections(handle, offset=offset, limit=limit)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_multi_slack_connections:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_multi_slack_connections: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**ManagedMultiConnectionListResponse**](ManagedMultiConnectionListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_multi_slack_routes**
> ManagedMultiRouteListResponse external_channel_v1_list_multi_slack_routes(connection_id, handle, offset=offset, limit=limit)

List Multi Slack Routes

List a paged Multi App Agent catalog, including removed routes.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_route_list_response import ManagedMultiRouteListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Multi Slack Routes
        api_response = api_instance.external_channel_v1_list_multi_slack_routes(connection_id, handle, offset=offset, limit=limit)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_multi_slack_routes:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_multi_slack_routes: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**ManagedMultiRouteListResponse**](ManagedMultiRouteListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_list_session_channels**
> ManagedBindingListResponse external_channel_v1_list_session_channels(agent_id, session_id, handle)

List Session Channels

List bindings, Channel Work, delivery outcomes, and Session grants.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_binding_list_response import ManagedBindingListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # List Session Channels
        api_response = api_instance.external_channel_v1_list_session_channels(agent_id, session_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_list_session_channels:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_list_session_channels: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedBindingListResponse**](ManagedBindingListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_load_multi_slack_management_handoff**
> ManagedSlackManagementHandoff external_channel_v1_load_multi_slack_management_handoff(interaction_id, handle)

Load Multi Slack Management Handoff

Load opaque Slack management state after authenticated Workspace recheck.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_slack_management_handoff import ManagedSlackManagementHandoff
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    interaction_id = 'interaction_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Load Multi Slack Management Handoff
        api_response = api_instance.external_channel_v1_load_multi_slack_management_handoff(interaction_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_load_multi_slack_management_handoff:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_load_multi_slack_management_handoff: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **interaction_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedSlackManagementHandoff**](ManagedSlackManagementHandoff.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_reenable_multi_discord_route**
> ManagedMultiRoute external_channel_v1_reenable_multi_discord_route(connection_id, route_id, handle)

Reenable Multi Discord Route

Re-enable a previously removed Multi App Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_route import ManagedMultiRoute
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    route_id = 'route_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Reenable Multi Discord Route
        api_response = api_instance.external_channel_v1_reenable_multi_discord_route(connection_id, route_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_reenable_multi_discord_route:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_reenable_multi_discord_route: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **route_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedMultiRoute**](ManagedMultiRoute.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_reenable_multi_slack_route**
> ManagedMultiRoute external_channel_v1_reenable_multi_slack_route(connection_id, route_id, handle)

Reenable Multi Slack Route

Re-enable a previously removed Multi App Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_route import ManagedMultiRoute
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    route_id = 'route_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Reenable Multi Slack Route
        api_response = api_instance.external_channel_v1_reenable_multi_slack_route(connection_id, route_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_reenable_multi_slack_route:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_reenable_multi_slack_route: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **route_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ManagedMultiRoute**](ManagedMultiRoute.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_remove_access_block**
> external_channel_v1_remove_access_block(agent_id, block_id, handle)

Remove Access Block

Remove one Agent-level external participant block.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    block_id = 'block_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Remove Access Block
        api_instance.external_channel_v1_remove_access_block(agent_id, block_id, handle)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_remove_access_block: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **block_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_remove_multi_discord_route**
> ExternalChannelMultiRouteImpact external_channel_v1_remove_multi_discord_route(connection_id, route_id, handle, generation_fence_request)

Remove Multi Discord Route

Generation-fence destructive removal of one Multi App Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_multi_route_impact import ExternalChannelMultiRouteImpact
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    route_id = 'route_id_example' # str | 
    handle = 'handle_example' # str | 
    generation_fence_request = azentspublicclient.GenerationFenceRequest() # GenerationFenceRequest | 

    try:
        # Remove Multi Discord Route
        api_response = api_instance.external_channel_v1_remove_multi_discord_route(connection_id, route_id, handle, generation_fence_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_remove_multi_discord_route:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_remove_multi_discord_route: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **route_id** | **str**|  | 
 **handle** | **str**|  | 
 **generation_fence_request** | [**GenerationFenceRequest**](GenerationFenceRequest.md)|  | 

### Return type

[**ExternalChannelMultiRouteImpact**](ExternalChannelMultiRouteImpact.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_remove_multi_slack_route**
> ExternalChannelMultiRouteImpact external_channel_v1_remove_multi_slack_route(connection_id, route_id, handle, generation_fence_request)

Remove Multi Slack Route

Generation-fence destructive removal of one Multi App Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_multi_route_impact import ExternalChannelMultiRouteImpact
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    route_id = 'route_id_example' # str | 
    handle = 'handle_example' # str | 
    generation_fence_request = azentspublicclient.GenerationFenceRequest() # GenerationFenceRequest | 

    try:
        # Remove Multi Slack Route
        api_response = api_instance.external_channel_v1_remove_multi_slack_route(connection_id, route_id, handle, generation_fence_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_remove_multi_slack_route:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_remove_multi_slack_route: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **route_id** | **str**|  | 
 **handle** | **str**|  | 
 **generation_fence_request** | [**GenerationFenceRequest**](GenerationFenceRequest.md)|  | 

### Return type

[**ExternalChannelMultiRouteImpact**](ExternalChannelMultiRouteImpact.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_replace_multi_discord_channel_default**
> ManagedChannelDefault external_channel_v1_replace_multi_discord_channel_default(connection_id, provider_channel_id, handle, multi_channel_default_request)

Replace Multi Discord Channel Default

Generation-fence replacement of one Multi App channel default.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_channel_default import ManagedChannelDefault
from azentspublicclient.models.multi_channel_default_request import MultiChannelDefaultRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    provider_channel_id = 'provider_channel_id_example' # str | 
    handle = 'handle_example' # str | 
    multi_channel_default_request = azentspublicclient.MultiChannelDefaultRequest() # MultiChannelDefaultRequest | 

    try:
        # Replace Multi Discord Channel Default
        api_response = api_instance.external_channel_v1_replace_multi_discord_channel_default(connection_id, provider_channel_id, handle, multi_channel_default_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_replace_multi_discord_channel_default:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_replace_multi_discord_channel_default: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **provider_channel_id** | **str**|  | 
 **handle** | **str**|  | 
 **multi_channel_default_request** | [**MultiChannelDefaultRequest**](MultiChannelDefaultRequest.md)|  | 

### Return type

[**ManagedChannelDefault**](ManagedChannelDefault.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_replace_multi_slack_channel_default**
> ManagedChannelDefault external_channel_v1_replace_multi_slack_channel_default(connection_id, provider_channel_id, handle, multi_channel_default_request)

Replace Multi Slack Channel Default

Generation-fence replacement of one Multi App channel default.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_channel_default import ManagedChannelDefault
from azentspublicclient.models.multi_channel_default_request import MultiChannelDefaultRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    provider_channel_id = 'provider_channel_id_example' # str | 
    handle = 'handle_example' # str | 
    multi_channel_default_request = azentspublicclient.MultiChannelDefaultRequest() # MultiChannelDefaultRequest | 

    try:
        # Replace Multi Slack Channel Default
        api_response = api_instance.external_channel_v1_replace_multi_slack_channel_default(connection_id, provider_channel_id, handle, multi_channel_default_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_replace_multi_slack_channel_default:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_replace_multi_slack_channel_default: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **provider_channel_id** | **str**|  | 
 **handle** | **str**|  | 
 **multi_channel_default_request** | [**MultiChannelDefaultRequest**](MultiChannelDefaultRequest.md)|  | 

### Return type

[**ManagedChannelDefault**](ManagedChannelDefault.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_revoke_access_grant**
> external_channel_v1_revoke_access_grant(agent_id, grant_id, handle)

Revoke Access Grant

Revoke one Agent- or Session-scoped external participant grant.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    grant_id = 'grant_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Revoke Access Grant
        api_instance.external_channel_v1_revoke_access_grant(agent_id, grant_id, handle)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_revoke_access_grant: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **grant_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_setup_discord_connection**
> ManagedConnectionSetup external_channel_v1_setup_discord_connection(agent_id, handle, discord_connection_setup_request)

Setup Discord Connection

Create a configuring dedicated Discord App and its sole Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.discord_connection_setup_request import DiscordConnectionSetupRequest
from azentspublicclient.models.managed_connection_setup import ManagedConnectionSetup
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    discord_connection_setup_request = azentspublicclient.DiscordConnectionSetupRequest() # DiscordConnectionSetupRequest | 

    try:
        # Setup Discord Connection
        api_response = api_instance.external_channel_v1_setup_discord_connection(agent_id, handle, discord_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_setup_discord_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_setup_discord_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **discord_connection_setup_request** | [**DiscordConnectionSetupRequest**](DiscordConnectionSetupRequest.md)|  | 

### Return type

[**ManagedConnectionSetup**](ManagedConnectionSetup.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_setup_multi_discord_connection**
> ManagedMultiConnectionSetup external_channel_v1_setup_multi_discord_connection(handle, discord_connection_setup_request)

Setup Multi Discord Connection

Create a zero-Agent-capable configuring Workspace Discord Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.discord_connection_setup_request import DiscordConnectionSetupRequest
from azentspublicclient.models.managed_multi_connection_setup import ManagedMultiConnectionSetup
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    handle = 'handle_example' # str | 
    discord_connection_setup_request = azentspublicclient.DiscordConnectionSetupRequest() # DiscordConnectionSetupRequest | 

    try:
        # Setup Multi Discord Connection
        api_response = api_instance.external_channel_v1_setup_multi_discord_connection(handle, discord_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_setup_multi_discord_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_setup_multi_discord_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **discord_connection_setup_request** | [**DiscordConnectionSetupRequest**](DiscordConnectionSetupRequest.md)|  | 

### Return type

[**ManagedMultiConnectionSetup**](ManagedMultiConnectionSetup.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_setup_multi_slack_connection**
> ManagedMultiConnectionSetup external_channel_v1_setup_multi_slack_connection(handle, slack_connection_setup_request)

Setup Multi Slack Connection

Create a zero-Agent-capable Workspace Slack Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_multi_connection_setup import ManagedMultiConnectionSetup
from azentspublicclient.models.slack_connection_setup_request import SlackConnectionSetupRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    handle = 'handle_example' # str | 
    slack_connection_setup_request = azentspublicclient.SlackConnectionSetupRequest() # SlackConnectionSetupRequest | 

    try:
        # Setup Multi Slack Connection
        api_response = api_instance.external_channel_v1_setup_multi_slack_connection(handle, slack_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_setup_multi_slack_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_setup_multi_slack_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **slack_connection_setup_request** | [**SlackConnectionSetupRequest**](SlackConnectionSetupRequest.md)|  | 

### Return type

[**ManagedMultiConnectionSetup**](ManagedMultiConnectionSetup.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_setup_slack_connection**
> ManagedConnectionSetup external_channel_v1_setup_slack_connection(agent_id, handle, slack_connection_setup_request)

Setup Slack Connection

Create a dedicated Slack App connection and active Agent route.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.managed_connection_setup import ManagedConnectionSetup
from azentspublicclient.models.slack_connection_setup_request import SlackConnectionSetupRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    slack_connection_setup_request = azentspublicclient.SlackConnectionSetupRequest() # SlackConnectionSetupRequest | 

    try:
        # Setup Slack Connection
        api_response = api_instance.external_channel_v1_setup_slack_connection(agent_id, handle, slack_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_setup_slack_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_setup_slack_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **slack_connection_setup_request** | [**SlackConnectionSetupRequest**](SlackConnectionSetupRequest.md)|  | 

### Return type

[**ManagedConnectionSetup**](ManagedConnectionSetup.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_update_connection_access_policy**
> ManagedConnection external_channel_v1_update_connection_access_policy(agent_id, connection_id, handle, connection_access_policy_request)

Update Connection Access Policy

Update open human access and external bot-message admission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.connection_access_policy_request import ConnectionAccessPolicyRequest
from azentspublicclient.models.managed_connection import ManagedConnection
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    connection_access_policy_request = azentspublicclient.ConnectionAccessPolicyRequest() # ConnectionAccessPolicyRequest | 

    try:
        # Update Connection Access Policy
        api_response = api_instance.external_channel_v1_update_connection_access_policy(agent_id, connection_id, handle, connection_access_policy_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_update_connection_access_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_update_connection_access_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **connection_access_policy_request** | [**ConnectionAccessPolicyRequest**](ConnectionAccessPolicyRequest.md)|  | 

### Return type

[**ManagedConnection**](ManagedConnection.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_update_discord_connection**
> ExternalChannelConnectionStatusSnapshot external_channel_v1_update_discord_connection(agent_id, connection_id, handle, discord_connection_setup_request)

Update Discord Connection

Replace a dedicated Discord App and reactivate callback authority.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.discord_connection_setup_request import DiscordConnectionSetupRequest
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    discord_connection_setup_request = azentspublicclient.DiscordConnectionSetupRequest() # DiscordConnectionSetupRequest | 

    try:
        # Update Discord Connection
        api_response = api_instance.external_channel_v1_update_discord_connection(agent_id, connection_id, handle, discord_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_update_discord_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_update_discord_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **discord_connection_setup_request** | [**DiscordConnectionSetupRequest**](DiscordConnectionSetupRequest.md)|  | 

### Return type

[**ExternalChannelConnectionStatusSnapshot**](ExternalChannelConnectionStatusSnapshot.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_update_multi_discord_connection**
> ExternalChannelConnectionStatusSnapshot external_channel_v1_update_multi_discord_connection(connection_id, handle, discord_connection_setup_request)

Update Multi Discord Connection

Replace a Discord Multi App and reactivate its callback authority.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.discord_connection_setup_request import DiscordConnectionSetupRequest
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    discord_connection_setup_request = azentspublicclient.DiscordConnectionSetupRequest() # DiscordConnectionSetupRequest | 

    try:
        # Update Multi Discord Connection
        api_response = api_instance.external_channel_v1_update_multi_discord_connection(connection_id, handle, discord_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_update_multi_discord_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_update_multi_discord_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **discord_connection_setup_request** | [**DiscordConnectionSetupRequest**](DiscordConnectionSetupRequest.md)|  | 

### Return type

[**ExternalChannelConnectionStatusSnapshot**](ExternalChannelConnectionStatusSnapshot.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_update_multi_slack_connection**
> ExternalChannelConnectionStatusSnapshot external_channel_v1_update_multi_slack_connection(connection_id, handle, slack_connection_setup_request)

Update Multi Slack Connection

Replace complete Slack Multi App setup and immediately validate it.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot
from azentspublicclient.models.slack_connection_setup_request import SlackConnectionSetupRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    slack_connection_setup_request = azentspublicclient.SlackConnectionSetupRequest() # SlackConnectionSetupRequest | 

    try:
        # Update Multi Slack Connection
        api_response = api_instance.external_channel_v1_update_multi_slack_connection(connection_id, handle, slack_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_update_multi_slack_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_update_multi_slack_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **slack_connection_setup_request** | [**SlackConnectionSetupRequest**](SlackConnectionSetupRequest.md)|  | 

### Return type

[**ExternalChannelConnectionStatusSnapshot**](ExternalChannelConnectionStatusSnapshot.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_update_slack_connection**
> ExternalChannelConnectionStatusSnapshot external_channel_v1_update_slack_connection(agent_id, connection_id, handle, slack_connection_setup_request)

Update Slack Connection

Replace the complete Slack setup and immediately validate it.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot
from azentspublicclient.models.slack_connection_setup_request import SlackConnectionSetupRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 
    slack_connection_setup_request = azentspublicclient.SlackConnectionSetupRequest() # SlackConnectionSetupRequest | 

    try:
        # Update Slack Connection
        api_response = api_instance.external_channel_v1_update_slack_connection(agent_id, connection_id, handle, slack_connection_setup_request)
        print("The response of ExternalChannelV1Api->external_channel_v1_update_slack_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_update_slack_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 
 **slack_connection_setup_request** | [**SlackConnectionSetupRequest**](SlackConnectionSetupRequest.md)|  | 

### Return type

[**ExternalChannelConnectionStatusSnapshot**](ExternalChannelConnectionStatusSnapshot.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_validate_connection**
> ExternalChannelConnectionStatusSnapshot external_channel_v1_validate_connection(agent_id, connection_id, handle)

Validate Connection

Validate credentials and activate or update sanitized connection health.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Validate Connection
        api_response = api_instance.external_channel_v1_validate_connection(agent_id, connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_validate_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_validate_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ExternalChannelConnectionStatusSnapshot**](ExternalChannelConnectionStatusSnapshot.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_validate_multi_discord_connection**
> ExternalChannelConnectionStatusSnapshot external_channel_v1_validate_multi_discord_connection(connection_id, handle)

Validate Multi Discord Connection

Validate one Workspace Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Validate Multi Discord Connection
        api_response = api_instance.external_channel_v1_validate_multi_discord_connection(connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_validate_multi_discord_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_validate_multi_discord_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ExternalChannelConnectionStatusSnapshot**](ExternalChannelConnectionStatusSnapshot.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **external_channel_v1_validate_multi_slack_connection**
> ExternalChannelConnectionStatusSnapshot external_channel_v1_validate_multi_slack_connection(connection_id, handle)

Validate Multi Slack Connection

Validate one Workspace Multi App.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ExternalChannelV1Api(api_client)
    connection_id = 'connection_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Validate Multi Slack Connection
        api_response = api_instance.external_channel_v1_validate_multi_slack_connection(connection_id, handle)
        print("The response of ExternalChannelV1Api->external_channel_v1_validate_multi_slack_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ExternalChannelV1Api->external_channel_v1_validate_multi_slack_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **connection_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ExternalChannelConnectionStatusSnapshot**](ExternalChannelConnectionStatusSnapshot.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

