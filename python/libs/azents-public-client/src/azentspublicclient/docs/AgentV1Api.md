# azentspublicclient.AgentV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**agent_v1_add_agent_admin**](AgentV1Api.md#agent_v1_add_agent_admin) | **POST** /agent/v1/workspaces/{handle}/agents/{agent_id}/admins | Add Agent Admin
[**agent_v1_create_agent**](AgentV1Api.md#agent_v1_create_agent) | **POST** /agent/v1/workspaces/{handle}/agents | Create Agent
[**agent_v1_create_agent_memory**](AgentV1Api.md#agent_v1_create_agent_memory) | **POST** /agent/v1/workspaces/{handle}/agents/{agent_id}/memories | Create Agent Memory
[**agent_v1_delete_agent**](AgentV1Api.md#agent_v1_delete_agent) | **DELETE** /agent/v1/workspaces/{handle}/agents/{agent_id} | Delete Agent
[**agent_v1_delete_agent_memory**](AgentV1Api.md#agent_v1_delete_agent_memory) | **DELETE** /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id} | Delete Agent Memory
[**agent_v1_finalize_avatar**](AgentV1Api.md#agent_v1_finalize_avatar) | **POST** /agent/v1/workspaces/{handle}/agents/{agent_id}/avatar/finalize | Finalize Avatar
[**agent_v1_get_agent**](AgentV1Api.md#agent_v1_get_agent) | **GET** /agent/v1/workspaces/{handle}/agents/{agent_id} | Get Agent
[**agent_v1_get_agent_memory**](AgentV1Api.md#agent_v1_get_agent_memory) | **GET** /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id} | Get Agent Memory
[**agent_v1_list_agent_admins**](AgentV1Api.md#agent_v1_list_agent_admins) | **GET** /agent/v1/workspaces/{handle}/agents/{agent_id}/admins | List Agent Admins
[**agent_v1_list_agent_memories**](AgentV1Api.md#agent_v1_list_agent_memories) | **GET** /agent/v1/workspaces/{handle}/agents/{agent_id}/memories | List Agent Memories
[**agent_v1_list_agents**](AgentV1Api.md#agent_v1_list_agents) | **GET** /agent/v1/workspaces/{handle}/agents | List Agents
[**agent_v1_remove_agent_admin**](AgentV1Api.md#agent_v1_remove_agent_admin) | **DELETE** /agent/v1/workspaces/{handle}/agents/{agent_id}/admins/{admin_workspace_user_id} | Remove Agent Admin
[**agent_v1_remove_avatar**](AgentV1Api.md#agent_v1_remove_avatar) | **DELETE** /agent/v1/workspaces/{handle}/agents/{agent_id}/avatar | Remove Avatar
[**agent_v1_request_avatar_upload**](AgentV1Api.md#agent_v1_request_avatar_upload) | **POST** /agent/v1/workspaces/{handle}/agents/{agent_id}/avatar/upload-url | Request Avatar Upload
[**agent_v1_update_agent**](AgentV1Api.md#agent_v1_update_agent) | **PATCH** /agent/v1/workspaces/{handle}/agents/{agent_id} | Update Agent
[**agent_v1_update_agent_memory**](AgentV1Api.md#agent_v1_update_agent_memory) | **PATCH** /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id} | Update Agent Memory


# **agent_v1_add_agent_admin**
> AgentAdminResponse agent_v1_add_agent_admin(agent_id, handle, agent_admin_add_request)

Add Agent Admin

Add an administrator to an Agent.

Only existing administrators or workspace owners can add one.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_admin_add_request import AgentAdminAddRequest
from azentspublicclient.models.agent_admin_response import AgentAdminResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    agent_admin_add_request = azentspublicclient.AgentAdminAddRequest() # AgentAdminAddRequest | 

    try:
        # Add Agent Admin
        api_response = api_instance.agent_v1_add_agent_admin(agent_id, handle, agent_admin_add_request)
        print("The response of AgentV1Api->agent_v1_add_agent_admin:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_add_agent_admin: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **agent_admin_add_request** | [**AgentAdminAddRequest**](AgentAdminAddRequest.md)|  | 

### Return type

[**AgentAdminResponse**](AgentAdminResponse.md)

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

# **agent_v1_create_agent**
> AgentResponse agent_v1_create_agent(handle, agent_create_request)

Create Agent

Create an Agent.

Any workspace member can create one.
The creator is automatically registered as the first administrator.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_response import AgentResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_create_request = azentspublicclient.AgentCreateRequest() # AgentCreateRequest | 

    try:
        # Create Agent
        api_response = api_instance.agent_v1_create_agent(handle, agent_create_request)
        print("The response of AgentV1Api->agent_v1_create_agent:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_create_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_create_request** | [**AgentCreateRequest**](AgentCreateRequest.md)|  | 

### Return type

[**AgentResponse**](AgentResponse.md)

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

# **agent_v1_create_agent_memory**
> MemoryResponse agent_v1_create_agent_memory(agent_id, handle, memory_create_request)

Create Agent Memory

Create Memory with strict conflict semantics.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.memory_create_request import MemoryCreateRequest
from azentspublicclient.models.memory_response import MemoryResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    memory_create_request = azentspublicclient.MemoryCreateRequest() # MemoryCreateRequest | 

    try:
        # Create Agent Memory
        api_response = api_instance.agent_v1_create_agent_memory(agent_id, handle, memory_create_request)
        print("The response of AgentV1Api->agent_v1_create_agent_memory:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_create_agent_memory: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **memory_create_request** | [**MemoryCreateRequest**](MemoryCreateRequest.md)|  | 

### Return type

[**MemoryResponse**](MemoryResponse.md)

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

# **agent_v1_delete_agent**
> AgentDecommissionResponse agent_v1_delete_agent(agent_id, handle)

Delete Agent

Request durable Agent decommission.

Only administrators or workspace owners can request it.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_decommission_response import AgentDecommissionResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Delete Agent
        api_response = api_instance.agent_v1_delete_agent(agent_id, handle)
        print("The response of AgentV1Api->agent_v1_delete_agent:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_delete_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**AgentDecommissionResponse**](AgentDecommissionResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **agent_v1_delete_agent_memory**
> agent_v1_delete_agent_memory(agent_id, memory_id, handle)

Delete Agent Memory

Delete one Memory by ID.

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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    memory_id = 'memory_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Delete Agent Memory
        api_instance.agent_v1_delete_agent_memory(agent_id, memory_id, handle)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_delete_agent_memory: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **memory_id** | **str**|  | 
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

# **agent_v1_finalize_avatar**
> AgentResponse agent_v1_finalize_avatar(agent_id, handle, avatar_finalize_request)

Finalize Avatar

Validate and resize the uploaded file, then apply it to the Agent.

The server downloads the actual bytes from S3 and reruns handler validation,
so it does not trust the client-reported size/type. On success, returns an
`AgentResponse` containing the new thumbnail URL.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.avatar_finalize_request import AvatarFinalizeRequest
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    avatar_finalize_request = azentspublicclient.AvatarFinalizeRequest() # AvatarFinalizeRequest | 

    try:
        # Finalize Avatar
        api_response = api_instance.agent_v1_finalize_avatar(agent_id, handle, avatar_finalize_request)
        print("The response of AgentV1Api->agent_v1_finalize_avatar:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_finalize_avatar: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **avatar_finalize_request** | [**AvatarFinalizeRequest**](AvatarFinalizeRequest.md)|  | 

### Return type

[**AgentResponse**](AgentResponse.md)

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

# **agent_v1_get_agent**
> AgentResponse agent_v1_get_agent(agent_id, handle)

Get Agent

Get Agent details.

Any workspace member can view them.
Private Agents are visible only to administrators and owners.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_response import AgentResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Agent
        api_response = api_instance.agent_v1_get_agent(agent_id, handle)
        print("The response of AgentV1Api->agent_v1_get_agent:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_get_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**AgentResponse**](AgentResponse.md)

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

# **agent_v1_get_agent_memory**
> MemoryResponse agent_v1_get_agent_memory(agent_id, memory_id, handle)

Get Agent Memory

Get one visible Memory by ID.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.memory_response import MemoryResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    memory_id = 'memory_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Agent Memory
        api_response = api_instance.agent_v1_get_agent_memory(agent_id, memory_id, handle)
        print("The response of AgentV1Api->agent_v1_get_agent_memory:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_get_agent_memory: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **memory_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**MemoryResponse**](MemoryResponse.md)

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

# **agent_v1_list_agent_admins**
> AgentAdminListResponse agent_v1_list_agent_admins(agent_id, handle)

List Agent Admins

List Agent administrators.

Any workspace member can view them.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_admin_list_response import AgentAdminListResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # List Agent Admins
        api_response = api_instance.agent_v1_list_agent_admins(agent_id, handle)
        print("The response of AgentV1Api->agent_v1_list_agent_admins:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_list_agent_admins: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**AgentAdminListResponse**](AgentAdminListResponse.md)

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

# **agent_v1_list_agent_memories**
> MemoryListResponse agent_v1_list_agent_memories(agent_id, handle, scope, type=type, query=query)

List Agent Memories

List memories for one Agent and scope.

Agent-scope Memory is readable by users who can view the Agent. User-scope
Memory lists only the current user's entries.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.memory_list_response import MemoryListResponse
from azentspublicclient.models.memory_scope import MemoryScope
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    scope = azentspublicclient.MemoryScope() # MemoryScope | Memory scope
    type = 'type_example' # str | Memory type filter (optional)
    query = 'query_example' # str | Search query (optional)

    try:
        # List Agent Memories
        api_response = api_instance.agent_v1_list_agent_memories(agent_id, handle, scope, type=type, query=query)
        print("The response of AgentV1Api->agent_v1_list_agent_memories:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_list_agent_memories: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **scope** | [**MemoryScope**](.md)| Memory scope | 
 **type** | **str**| Memory type filter | [optional] 
 **query** | **str**| Search query | [optional] 

### Return type

[**MemoryListResponse**](MemoryListResponse.md)

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

# **agent_v1_list_agents**
> AgentListResponse agent_v1_list_agents(handle)

List Agents

List Agents in a workspace.

Any workspace member can list Agents.
Public Agents are visible to everyone; private Agents are visible only to
administrators and owners.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_list_response import AgentListResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # List Agents
        api_response = api_instance.agent_v1_list_agents(handle)
        print("The response of AgentV1Api->agent_v1_list_agents:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_list_agents: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**AgentListResponse**](AgentListResponse.md)

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

# **agent_v1_remove_agent_admin**
> agent_v1_remove_agent_admin(agent_id, admin_workspace_user_id, handle)

Remove Agent Admin

Remove an administrator from an Agent.

Only existing administrators or workspace owners can remove one.
The last administrator cannot be removed.

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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    admin_workspace_user_id = 'admin_workspace_user_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Remove Agent Admin
        api_instance.agent_v1_remove_agent_admin(agent_id, admin_workspace_user_id, handle)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_remove_agent_admin: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **admin_workspace_user_id** | **str**|  | 
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

# **agent_v1_remove_avatar**
> AgentResponse agent_v1_remove_avatar(agent_id, handle)

Remove Avatar

Remove an Agent avatar.

Only administrators or workspace owners can do this. Existing thumbnails in
S3 are deleted best-effort, and garbage-collected by Lifecycle on failure.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_response import AgentResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Remove Avatar
        api_response = api_instance.agent_v1_remove_avatar(agent_id, handle)
        print("The response of AgentV1Api->agent_v1_remove_avatar:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_remove_avatar: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**AgentResponse**](AgentResponse.md)

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

# **agent_v1_request_avatar_upload**
> AvatarUploadTicketResponse agent_v1_request_avatar_upload(agent_id, handle, avatar_upload_request)

Request Avatar Upload

Issue a presigned PUT ticket for avatar upload.

Only administrators or workspace owners can do this. The ticket TTL is the
server constant of 10 minutes. The client uploads the file directly with a
PUT request to the issued `upload_url`, then calls the `finalize` endpoint.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.avatar_upload_request import AvatarUploadRequest
from azentspublicclient.models.avatar_upload_ticket_response import AvatarUploadTicketResponse
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    avatar_upload_request = azentspublicclient.AvatarUploadRequest() # AvatarUploadRequest | 

    try:
        # Request Avatar Upload
        api_response = api_instance.agent_v1_request_avatar_upload(agent_id, handle, avatar_upload_request)
        print("The response of AgentV1Api->agent_v1_request_avatar_upload:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_request_avatar_upload: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **avatar_upload_request** | [**AvatarUploadRequest**](AvatarUploadRequest.md)|  | 

### Return type

[**AvatarUploadTicketResponse**](AvatarUploadTicketResponse.md)

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

# **agent_v1_update_agent**
> AgentResponse agent_v1_update_agent(agent_id, handle, agent_update_request)

Update Agent

Update an Agent.

Only administrators or workspace owners can update it.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_update_request import AgentUpdateRequest
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    agent_update_request = azentspublicclient.AgentUpdateRequest() # AgentUpdateRequest | 

    try:
        # Update Agent
        api_response = api_instance.agent_v1_update_agent(agent_id, handle, agent_update_request)
        print("The response of AgentV1Api->agent_v1_update_agent:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_update_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **agent_update_request** | [**AgentUpdateRequest**](AgentUpdateRequest.md)|  | 

### Return type

[**AgentResponse**](AgentResponse.md)

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

# **agent_v1_update_agent_memory**
> MemoryResponse agent_v1_update_agent_memory(agent_id, memory_id, handle, memory_update_request)

Update Agent Memory

Update one Memory by ID.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.memory_response import MemoryResponse
from azentspublicclient.models.memory_update_request import MemoryUpdateRequest
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
    api_instance = azentspublicclient.AgentV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    memory_id = 'memory_id_example' # str | 
    handle = 'handle_example' # str | 
    memory_update_request = azentspublicclient.MemoryUpdateRequest() # MemoryUpdateRequest | 

    try:
        # Update Agent Memory
        api_response = api_instance.agent_v1_update_agent_memory(agent_id, memory_id, handle, memory_update_request)
        print("The response of AgentV1Api->agent_v1_update_agent_memory:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentV1Api->agent_v1_update_agent_memory: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **memory_id** | **str**|  | 
 **handle** | **str**|  | 
 **memory_update_request** | [**MemoryUpdateRequest**](MemoryUpdateRequest.md)|  | 

### Return type

[**MemoryResponse**](MemoryResponse.md)

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

