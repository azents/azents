# azentspublicclient.WorkspaceV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workspace_v1_bootstrap_first_owner**](WorkspaceV1Api.md#workspace_v1_bootstrap_first_owner) | **POST** /workspace/v1/bootstrap/first-owner | Bootstrap First Owner
[**workspace_v1_create_workspace**](WorkspaceV1Api.md#workspace_v1_create_workspace) | **POST** /workspace/v1/workspaces | Create Workspace
[**workspace_v1_get_bootstrap_status**](WorkspaceV1Api.md#workspace_v1_get_bootstrap_status) | **GET** /workspace/v1/bootstrap/status | Get Bootstrap Status
[**workspace_v1_get_workspace_by_handle**](WorkspaceV1Api.md#workspace_v1_get_workspace_by_handle) | **GET** /workspace/v1/workspaces/{handle} | Get Workspace By Handle
[**workspace_v1_list_workspaces**](WorkspaceV1Api.md#workspace_v1_list_workspaces) | **GET** /workspace/v1/workspaces | List Workspaces


# **workspace_v1_bootstrap_first_owner**
> BootstrapFirstOwnerResponse workspace_v1_bootstrap_first_owner(bootstrap_first_owner_request)

Bootstrap First Owner

Create the first Owner and Workspace.

This endpoint is intentionally public because normal authentication cannot
exist before the first user. The service allows it only when user count is
zero and first-owner bootstrap is enabled.

### Example


```python
import azentspublicclient
from azentspublicclient.models.bootstrap_first_owner_request import BootstrapFirstOwnerRequest
from azentspublicclient.models.bootstrap_first_owner_response import BootstrapFirstOwnerResponse
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
    bootstrap_first_owner_request = azentspublicclient.BootstrapFirstOwnerRequest() # BootstrapFirstOwnerRequest | 

    try:
        # Bootstrap First Owner
        api_response = api_instance.workspace_v1_bootstrap_first_owner(bootstrap_first_owner_request)
        print("The response of WorkspaceV1Api->workspace_v1_bootstrap_first_owner:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_bootstrap_first_owner: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **bootstrap_first_owner_request** | [**BootstrapFirstOwnerRequest**](BootstrapFirstOwnerRequest.md)|  | 

### Return type

[**BootstrapFirstOwnerResponse**](BootstrapFirstOwnerResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

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

# **workspace_v1_get_bootstrap_status**
> BootstrapStatusResponse workspace_v1_get_bootstrap_status()

Get Bootstrap Status

Get whether first owner bootstrap is available.

This endpoint is intentionally public because it is available only before
the first user exists and is gated by server-side bootstrap invariants.

### Example


```python
import azentspublicclient
from azentspublicclient.models.bootstrap_status_response import BootstrapStatusResponse
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

    try:
        # Get Bootstrap Status
        api_response = api_instance.workspace_v1_get_bootstrap_status()
        print("The response of WorkspaceV1Api->workspace_v1_get_bootstrap_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_get_bootstrap_status: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**BootstrapStatusResponse**](BootstrapStatusResponse.md)

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

