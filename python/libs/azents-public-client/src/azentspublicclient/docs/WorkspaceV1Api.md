# azentspublicclient.WorkspaceV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workspace_v1_create_workspace**](WorkspaceV1Api.md#workspace_v1_create_workspace) | **POST** /workspace/v1/workspaces | Create Workspace
[**workspace_v1_get_agent_environment_selection**](WorkspaceV1Api.md#workspace_v1_get_agent_environment_selection) | **GET** /workspace/v1/workspaces/{handle}/agents/{agent_id}/environment-selection | Get Agent Environment Selection
[**workspace_v1_get_workspace_by_handle**](WorkspaceV1Api.md#workspace_v1_get_workspace_by_handle) | **GET** /workspace/v1/workspaces/{handle} | Get Workspace By Handle
[**workspace_v1_get_workspace_environment**](WorkspaceV1Api.md#workspace_v1_get_workspace_environment) | **GET** /workspace/v1/workspaces/{handle}/environment | Get Workspace Environment
[**workspace_v1_list_workspaces**](WorkspaceV1Api.md#workspace_v1_list_workspaces) | **GET** /workspace/v1/workspaces | List Workspaces
[**workspace_v1_replace_agent_environment_selection**](WorkspaceV1Api.md#workspace_v1_replace_agent_environment_selection) | **PUT** /workspace/v1/workspaces/{handle}/agents/{agent_id}/environment-selection | Replace Agent Environment Selection
[**workspace_v1_replace_workspace_environment**](WorkspaceV1Api.md#workspace_v1_replace_workspace_environment) | **PUT** /workspace/v1/workspaces/{handle}/environment | Replace Workspace Environment


# **workspace_v1_create_workspace**
> CreateWorkspaceResponse workspace_v1_create_workspace(create_workspace_request)

Create Workspace

Create a Workspace and register the current user as Owner.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.create_workspace_response import CreateWorkspaceResponse
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
    api_instance = azentspublicclient.WorkspaceV1Api(api_client)
    create_workspace_request = azentspublicclient.CreateWorkspaceRequest() # CreateWorkspaceRequest | 

    try:
        # Create Workspace
        api_response = api_instance.workspace_v1_create_workspace(create_workspace_request)
        print("The response of WorkspaceV1Api->workspace_v1_create_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_create_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **create_workspace_request** | [**CreateWorkspaceRequest**](CreateWorkspaceRequest.md)|  | 

### Return type

[**CreateWorkspaceResponse**](CreateWorkspaceResponse.md)

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

# **workspace_v1_get_agent_environment_selection**
> AgentWorkspaceEnvironmentSettings workspace_v1_get_agent_environment_selection(agent_id, handle)

Get Agent Environment Selection

Get opt-in metadata for an accessible Agent in this Workspace.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_environment_settings import AgentWorkspaceEnvironmentSettings
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
    api_instance = azentspublicclient.WorkspaceV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Agent Environment Selection
        api_response = api_instance.workspace_v1_get_agent_environment_selection(agent_id, handle)
        print("The response of WorkspaceV1Api->workspace_v1_get_agent_environment_selection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_get_agent_environment_selection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**AgentWorkspaceEnvironmentSettings**](AgentWorkspaceEnvironmentSettings.md)

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

# **workspace_v1_get_workspace_by_handle**
> WorkspaceResponse workspace_v1_get_workspace_by_handle(handle)

Get Workspace By Handle

Get a Workspace by handle.

### Example


```python
import azentspublicclient
from azentspublicclient.models.workspace_response import WorkspaceResponse
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
    api_instance = azentspublicclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Workspace By Handle
        api_response = api_instance.workspace_v1_get_workspace_by_handle(handle)
        print("The response of WorkspaceV1Api->workspace_v1_get_workspace_by_handle:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_get_workspace_by_handle: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**WorkspaceResponse**](WorkspaceResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_get_workspace_environment**
> WorkspaceEnvironmentSettings workspace_v1_get_workspace_environment(handle)

Get Workspace Environment

List shared variable names without revealing values.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_environment_settings import WorkspaceEnvironmentSettings
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
    api_instance = azentspublicclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Workspace Environment
        api_response = api_instance.workspace_v1_get_workspace_environment(handle)
        print("The response of WorkspaceV1Api->workspace_v1_get_workspace_environment:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_get_workspace_environment: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**WorkspaceEnvironmentSettings**](WorkspaceEnvironmentSettings.md)

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

# **workspace_v1_list_workspaces**
> WorkspaceListResponse workspace_v1_list_workspaces()

List Workspaces

List Workspaces the current user belongs to.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_list_response import WorkspaceListResponse
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
    api_instance = azentspublicclient.WorkspaceV1Api(api_client)

    try:
        # List Workspaces
        api_response = api_instance.workspace_v1_list_workspaces()
        print("The response of WorkspaceV1Api->workspace_v1_list_workspaces:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_list_workspaces: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**WorkspaceListResponse**](WorkspaceListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_replace_agent_environment_selection**
> AgentWorkspaceEnvironmentSettings workspace_v1_replace_agent_environment_selection(agent_id, handle, agent_workspace_environment_replace)

Replace Agent Environment Selection

Choose exact shared identities; never implicitly opt in to new keys.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_environment_replace import AgentWorkspaceEnvironmentReplace
from azentspublicclient.models.agent_workspace_environment_settings import AgentWorkspaceEnvironmentSettings
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
    api_instance = azentspublicclient.WorkspaceV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    agent_workspace_environment_replace = azentspublicclient.AgentWorkspaceEnvironmentReplace() # AgentWorkspaceEnvironmentReplace | 

    try:
        # Replace Agent Environment Selection
        api_response = api_instance.workspace_v1_replace_agent_environment_selection(agent_id, handle, agent_workspace_environment_replace)
        print("The response of WorkspaceV1Api->workspace_v1_replace_agent_environment_selection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_replace_agent_environment_selection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **agent_workspace_environment_replace** | [**AgentWorkspaceEnvironmentReplace**](AgentWorkspaceEnvironmentReplace.md)|  | 

### Return type

[**AgentWorkspaceEnvironmentSettings**](AgentWorkspaceEnvironmentSettings.md)

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

# **workspace_v1_replace_workspace_environment**
> WorkspaceEnvironmentSettings workspace_v1_replace_workspace_environment(handle, workspace_environment_replace)

Replace Workspace Environment

Atomically replace the Workspace catalog under Owner/Manager authority.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_environment_replace import WorkspaceEnvironmentReplace
from azentspublicclient.models.workspace_environment_settings import WorkspaceEnvironmentSettings
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
    api_instance = azentspublicclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 
    workspace_environment_replace = azentspublicclient.WorkspaceEnvironmentReplace() # WorkspaceEnvironmentReplace | 

    try:
        # Replace Workspace Environment
        api_response = api_instance.workspace_v1_replace_workspace_environment(handle, workspace_environment_replace)
        print("The response of WorkspaceV1Api->workspace_v1_replace_workspace_environment:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_replace_workspace_environment: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **workspace_environment_replace** | [**WorkspaceEnvironmentReplace**](WorkspaceEnvironmentReplace.md)|  | 

### Return type

[**WorkspaceEnvironmentSettings**](WorkspaceEnvironmentSettings.md)

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

