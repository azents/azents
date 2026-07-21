# azentsadminclient.WorkspaceV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workspace_v1_create_workspace**](WorkspaceV1Api.md#workspace_v1_create_workspace) | **POST** /workspace/v1/workspaces | Create Workspace
[**workspace_v1_get_workspace**](WorkspaceV1Api.md#workspace_v1_get_workspace) | **GET** /workspace/v1/workspaces/{handle} | Get Workspace
[**workspace_v1_list_workspaces**](WorkspaceV1Api.md#workspace_v1_list_workspaces) | **GET** /workspace/v1/workspaces | List Workspaces
[**workspace_v1_update_workspace**](WorkspaceV1Api.md#workspace_v1_update_workspace) | **PATCH** /workspace/v1/workspaces/{handle} | Update Workspace


# **workspace_v1_create_workspace**
> WorkspaceResponse workspace_v1_create_workspace(workspace_create_request)

Create Workspace

Create a Workspace.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.workspace_create_request import WorkspaceCreateRequest
from azentsadminclient.models.workspace_response import WorkspaceResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    workspace_create_request = azentsadminclient.WorkspaceCreateRequest() # WorkspaceCreateRequest | 

    try:
        # Create Workspace
        api_response = api_instance.workspace_v1_create_workspace(workspace_create_request)
        print("The response of WorkspaceV1Api->workspace_v1_create_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_create_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_create_request** | [**WorkspaceCreateRequest**](WorkspaceCreateRequest.md)|  | 

### Return type

[**WorkspaceResponse**](WorkspaceResponse.md)

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

# **workspace_v1_get_workspace**
> WorkspaceResponse workspace_v1_get_workspace(handle)

Get Workspace

Get a Workspace by handle.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.workspace_response import WorkspaceResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Workspace
        api_response = api_instance.workspace_v1_get_workspace(handle)
        print("The response of WorkspaceV1Api->workspace_v1_get_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_get_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**WorkspaceResponse**](WorkspaceResponse.md)

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

List all Workspaces.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.workspace_list_response import WorkspaceListResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)

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

# **workspace_v1_update_workspace**
> WorkspaceResponse workspace_v1_update_workspace(handle, workspace_update_request)

Update Workspace

Update a Workspace.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.workspace_response import WorkspaceResponse
from azentsadminclient.models.workspace_update_request import WorkspaceUpdateRequest
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 
    workspace_update_request = azentsadminclient.WorkspaceUpdateRequest() # WorkspaceUpdateRequest | 

    try:
        # Update Workspace
        api_response = api_instance.workspace_v1_update_workspace(handle, workspace_update_request)
        print("The response of WorkspaceV1Api->workspace_v1_update_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_update_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **workspace_update_request** | [**WorkspaceUpdateRequest**](WorkspaceUpdateRequest.md)|  | 

### Return type

[**WorkspaceResponse**](WorkspaceResponse.md)

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

