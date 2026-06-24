# azentspublicclient.ToolkitV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**toolkit_v1_attach_toolkit_to_agent**](ToolkitV1Api.md#toolkit_v1_attach_toolkit_to_agent) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkits | Attach Toolkit To Agent
[**toolkit_v1_create_toolkit_config**](ToolkitV1Api.md#toolkit_v1_create_toolkit_config) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs | Create Toolkit Config
[**toolkit_v1_create_toolkit_scope**](ToolkitV1Api.md#toolkit_v1_create_toolkit_scope) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/scopes | Create Toolkit Scope
[**toolkit_v1_delete_toolkit_config**](ToolkitV1Api.md#toolkit_v1_delete_toolkit_config) | **DELETE** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id} | Delete Toolkit Config
[**toolkit_v1_delete_toolkit_scope**](ToolkitV1Api.md#toolkit_v1_delete_toolkit_scope) | **DELETE** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/scopes/{scope_id} | Delete Toolkit Scope
[**toolkit_v1_detach_toolkit_from_agent**](ToolkitV1Api.md#toolkit_v1_detach_toolkit_from_agent) | **DELETE** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkits/{agent_toolkit_id} | Detach Toolkit From Agent
[**toolkit_v1_get_toolkit_config**](ToolkitV1Api.md#toolkit_v1_get_toolkit_config) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id} | Get Toolkit Config
[**toolkit_v1_list_agent_toolkits**](ToolkitV1Api.md#toolkit_v1_list_agent_toolkits) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkits | List Agent Toolkits
[**toolkit_v1_list_available_toolkit_configs**](ToolkitV1Api.md#toolkit_v1_list_available_toolkit_configs) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs/available | List Available Toolkit Configs
[**toolkit_v1_list_toolkit_configs**](ToolkitV1Api.md#toolkit_v1_list_toolkit_configs) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs | List Toolkit Configs
[**toolkit_v1_list_toolkit_scopes**](ToolkitV1Api.md#toolkit_v1_list_toolkit_scopes) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/scopes | List Toolkit Scopes
[**toolkit_v1_list_toolkits**](ToolkitV1Api.md#toolkit_v1_list_toolkits) | **GET** /toolkit/v1/toolkits | List Toolkits
[**toolkit_v1_update_toolkit_config**](ToolkitV1Api.md#toolkit_v1_update_toolkit_config) | **PATCH** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id} | Update Toolkit Config


# **toolkit_v1_attach_toolkit_to_agent**
> AgentToolkitResponse toolkit_v1_attach_toolkit_to_agent(agent_id, handle, agent_toolkit_attach_request)

Attach Toolkit To Agent

Attach a Toolkit to an Agent.

Requires Toolkit read permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_toolkit_attach_request import AgentToolkitAttachRequest
from azentspublicclient.models.agent_toolkit_response import AgentToolkitResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |
    agent_toolkit_attach_request = azentspublicclient.AgentToolkitAttachRequest() # AgentToolkitAttachRequest |

    try:
        # Attach Toolkit To Agent
        api_response = api_instance.toolkit_v1_attach_toolkit_to_agent(agent_id, handle, agent_toolkit_attach_request)
        print("The response of ToolkitV1Api->toolkit_v1_attach_toolkit_to_agent:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_attach_toolkit_to_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |
 **agent_toolkit_attach_request** | [**AgentToolkitAttachRequest**](AgentToolkitAttachRequest.md)|  |

### Return type

[**AgentToolkitResponse**](AgentToolkitResponse.md)

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

# **toolkit_v1_create_toolkit_config**
> ToolkitConfigResponse toolkit_v1_create_toolkit_config(handle, toolkit_config_create_request)

Create Toolkit Config

Create a Toolkit Config.

Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.toolkit_config_create_request import ToolkitConfigCreateRequest
from azentspublicclient.models.toolkit_config_response import ToolkitConfigResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    handle = 'handle_example' # str |
    toolkit_config_create_request = azentspublicclient.ToolkitConfigCreateRequest() # ToolkitConfigCreateRequest |

    try:
        # Create Toolkit Config
        api_response = api_instance.toolkit_v1_create_toolkit_config(handle, toolkit_config_create_request)
        print("The response of ToolkitV1Api->toolkit_v1_create_toolkit_config:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_create_toolkit_config: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **toolkit_config_create_request** | [**ToolkitConfigCreateRequest**](ToolkitConfigCreateRequest.md)|  |

### Return type

[**ToolkitConfigResponse**](ToolkitConfigResponse.md)

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

# **toolkit_v1_create_toolkit_scope**
> ToolkitScopeResponse toolkit_v1_create_toolkit_scope(toolkit_config_id, handle)

Create Toolkit Scope

Create a Toolkit Scope.

Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.toolkit_scope_response import ToolkitScopeResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    toolkit_config_id = 'toolkit_config_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Create Toolkit Scope
        api_response = api_instance.toolkit_v1_create_toolkit_scope(toolkit_config_id, handle)
        print("The response of ToolkitV1Api->toolkit_v1_create_toolkit_scope:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_create_toolkit_scope: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_config_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**ToolkitScopeResponse**](ToolkitScopeResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **toolkit_v1_delete_toolkit_config**
> toolkit_v1_delete_toolkit_config(toolkit_config_id, handle)

Delete Toolkit Config

Delete a Toolkit Config.

Requires Toolkit write permission.

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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    toolkit_config_id = 'toolkit_config_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Delete Toolkit Config
        api_instance.toolkit_v1_delete_toolkit_config(toolkit_config_id, handle)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_delete_toolkit_config: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_config_id** | **str**|  |
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

# **toolkit_v1_delete_toolkit_scope**
> toolkit_v1_delete_toolkit_scope(toolkit_config_id, scope_id, handle)

Delete Toolkit Scope

Delete a Toolkit Scope.

Requires Toolkit write permission.

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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    toolkit_config_id = 'toolkit_config_id_example' # str |
    scope_id = 'scope_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Delete Toolkit Scope
        api_instance.toolkit_v1_delete_toolkit_scope(toolkit_config_id, scope_id, handle)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_delete_toolkit_scope: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_config_id** | **str**|  |
 **scope_id** | **str**|  |
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

# **toolkit_v1_detach_toolkit_from_agent**
> toolkit_v1_detach_toolkit_from_agent(agent_id, agent_toolkit_id, handle)

Detach Toolkit From Agent

Detach a Toolkit from an Agent.

Requires Toolkit read permission.

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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    agent_toolkit_id = 'agent_toolkit_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Detach Toolkit From Agent
        api_instance.toolkit_v1_detach_toolkit_from_agent(agent_id, agent_toolkit_id, handle)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_detach_toolkit_from_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **agent_toolkit_id** | **str**|  |
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

# **toolkit_v1_get_toolkit_config**
> ToolkitConfigResponse toolkit_v1_get_toolkit_config(toolkit_config_id, handle)

Get Toolkit Config

Get Toolkit Config details.

Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.toolkit_config_response import ToolkitConfigResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    toolkit_config_id = 'toolkit_config_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Get Toolkit Config
        api_response = api_instance.toolkit_v1_get_toolkit_config(toolkit_config_id, handle)
        print("The response of ToolkitV1Api->toolkit_v1_get_toolkit_config:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_get_toolkit_config: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_config_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**ToolkitConfigResponse**](ToolkitConfigResponse.md)

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

# **toolkit_v1_list_agent_toolkits**
> AgentToolkitListResponse toolkit_v1_list_agent_toolkits(agent_id, handle)

List Agent Toolkits

List Toolkits attached to an Agent.

Requires Toolkit read permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_toolkit_list_response import AgentToolkitListResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # List Agent Toolkits
        api_response = api_instance.toolkit_v1_list_agent_toolkits(agent_id, handle)
        print("The response of ToolkitV1Api->toolkit_v1_list_agent_toolkits:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_list_agent_toolkits: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**AgentToolkitListResponse**](AgentToolkitListResponse.md)

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

# **toolkit_v1_list_available_toolkit_configs**
> ToolkitConfigListResponse toolkit_v1_list_available_toolkit_configs(handle)

List Available Toolkit Configs

List Toolkit Configs available to the current user.

Requires Toolkit read permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.toolkit_config_list_response import ToolkitConfigListResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # List Available Toolkit Configs
        api_response = api_instance.toolkit_v1_list_available_toolkit_configs(handle)
        print("The response of ToolkitV1Api->toolkit_v1_list_available_toolkit_configs:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_list_available_toolkit_configs: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**ToolkitConfigListResponse**](ToolkitConfigListResponse.md)

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

# **toolkit_v1_list_toolkit_configs**
> ToolkitConfigListResponse toolkit_v1_list_toolkit_configs(handle)

List Toolkit Configs

List Toolkit Configs in a workspace.

Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.toolkit_config_list_response import ToolkitConfigListResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # List Toolkit Configs
        api_response = api_instance.toolkit_v1_list_toolkit_configs(handle)
        print("The response of ToolkitV1Api->toolkit_v1_list_toolkit_configs:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_list_toolkit_configs: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**ToolkitConfigListResponse**](ToolkitConfigListResponse.md)

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

# **toolkit_v1_list_toolkit_scopes**
> ToolkitScopeListResponse toolkit_v1_list_toolkit_scopes(toolkit_config_id, handle)

List Toolkit Scopes

List Scopes for a Toolkit.

Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.toolkit_scope_list_response import ToolkitScopeListResponse
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    toolkit_config_id = 'toolkit_config_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # List Toolkit Scopes
        api_response = api_instance.toolkit_v1_list_toolkit_scopes(toolkit_config_id, handle)
        print("The response of ToolkitV1Api->toolkit_v1_list_toolkit_scopes:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_list_toolkit_scopes: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_config_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**ToolkitScopeListResponse**](ToolkitScopeListResponse.md)

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

# **toolkit_v1_list_toolkits**
> ToolkitListResponse toolkit_v1_list_toolkits()

List Toolkits

Return the list of Toolkits provided by the platform.

Returns metadata for every tool registered in toolkit_registry.
Accessible without authentication.

### Example


```python
import azentspublicclient
from azentspublicclient.models.toolkit_list_response import ToolkitListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.ToolkitV1Api(api_client)

    try:
        # List Toolkits
        api_response = api_instance.toolkit_v1_list_toolkits()
        print("The response of ToolkitV1Api->toolkit_v1_list_toolkits:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_list_toolkits: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**ToolkitListResponse**](ToolkitListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **toolkit_v1_update_toolkit_config**
> ToolkitConfigResponse toolkit_v1_update_toolkit_config(toolkit_config_id, handle, toolkit_config_update_request)

Update Toolkit Config

Update a Toolkit Config.

Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.toolkit_config_response import ToolkitConfigResponse
from azentspublicclient.models.toolkit_config_update_request import ToolkitConfigUpdateRequest
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
    api_instance = azentspublicclient.ToolkitV1Api(api_client)
    toolkit_config_id = 'toolkit_config_id_example' # str |
    handle = 'handle_example' # str |
    toolkit_config_update_request = azentspublicclient.ToolkitConfigUpdateRequest() # ToolkitConfigUpdateRequest |

    try:
        # Update Toolkit Config
        api_response = api_instance.toolkit_v1_update_toolkit_config(toolkit_config_id, handle, toolkit_config_update_request)
        print("The response of ToolkitV1Api->toolkit_v1_update_toolkit_config:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitV1Api->toolkit_v1_update_toolkit_config: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_config_id** | **str**|  |
 **handle** | **str**|  |
 **toolkit_config_update_request** | [**ToolkitConfigUpdateRequest**](ToolkitConfigUpdateRequest.md)|  |

### Return type

[**ToolkitConfigResponse**](ToolkitConfigResponse.md)

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
