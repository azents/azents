# azentspublicclient.ExternalChannelV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**external_channel_v1_decide_approval_request**](ExternalChannelV1Api.md#external_channel_v1_decide_approval_request) | **POST** /external-channel/v1/approval-requests/{access_request_id}/decision | Decide Approval Request
[**external_channel_v1_disconnect_connection**](ExternalChannelV1Api.md#external_channel_v1_disconnect_connection) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id} | Disconnect Connection
[**external_channel_v1_disconnect_session_channel**](ExternalChannelV1Api.md#external_channel_v1_disconnect_session_channel) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels/{binding_id} | Disconnect Session Channel
[**external_channel_v1_get_approval_request**](ExternalChannelV1Api.md#external_channel_v1_get_approval_request) | **GET** /external-channel/v1/approval-requests/{access_request_id} | Get Approval Request
[**external_channel_v1_get_manifest_guidance**](ExternalChannelV1Api.md#external_channel_v1_get_manifest_guidance) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/manifest | Get Manifest Guidance
[**external_channel_v1_list_agent_access**](ExternalChannelV1Api.md#external_channel_v1_list_agent_access) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access | List Agent Access
[**external_channel_v1_list_connections**](ExternalChannelV1Api.md#external_channel_v1_list_connections) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels | List Connections
[**external_channel_v1_list_session_channels**](ExternalChannelV1Api.md#external_channel_v1_list_session_channels) | **GET** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels | List Session Channels
[**external_channel_v1_remove_access_block**](ExternalChannelV1Api.md#external_channel_v1_remove_access_block) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access/blocks/{block_id} | Remove Access Block
[**external_channel_v1_revoke_access_grant**](ExternalChannelV1Api.md#external_channel_v1_revoke_access_grant) | **DELETE** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access/grants/{grant_id} | Revoke Access Grant
[**external_channel_v1_setup_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_setup_slack_connection) | **POST** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/slack | Setup Slack Connection
[**external_channel_v1_update_slack_connection**](ExternalChannelV1Api.md#external_channel_v1_update_slack_connection) | **PUT** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/slack | Update Slack Connection
[**external_channel_v1_validate_connection**](ExternalChannelV1Api.md#external_channel_v1_validate_connection) | **POST** /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/validate | Validate Connection


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

Terminally disconnect a connection after one-attempt progress cleanup.

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

